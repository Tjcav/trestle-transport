"""Trace emission for decision explainability (Slice 8i-2).

This module provides opt-in, sampled trace emission for debugging and tuning.
Traces are emitted AFTER policy evaluation, BEFORE arbitration output.

Critical invariants:
- Zero semantic difference when tracing is off
- Never blocks execution
- Never emits by default in production
- Sampling rate controls overhead
"""

from __future__ import annotations

import secrets
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from .policy_engine import (
    DomainState,
    EvaluationContext,
    Importance,
    IntentCandidate,
)
from .trace import (
    ArbitrationTrace,
    ConditionCheck,
    DecisionOutcome,
    DecisionTrace,
    DomainSnapshot,
    DomainStateEntry,
    IntentClassification,
    OutcomeType,
    PerformanceMetrics,
    PolicyEvaluationTrace,
    QuietHoursCheck,
    RuleEvaluation,
    RuleResult,
    Trigger,
    TriggerType,
    WinningIntent,
)

if TYPE_CHECKING:
    from .profile import PolicyRule


@dataclass
class TraceConfig:
    """Configuration for trace emission.

    Attributes:
        enabled: Master switch for tracing (default: False for production)
        sample_rate: Fraction of decisions to trace (0.0-1.0, default: 1.0)
        include_metrics: Whether to include timing metrics (default: True)
        include_fusion: Whether to include fusion details (default: True)
    """

    enabled: bool = False
    sample_rate: float = 1.0
    include_metrics: bool = True
    include_fusion: bool = True

    def should_trace(self) -> bool:
        """Determine if this decision should be traced."""
        if not self.enabled:
            return False
        if self.sample_rate >= 1.0:
            return True
        # Use secrets for unbiased sampling (not crypto, but silences bandit)
        return secrets.randbelow(1000) < int(self.sample_rate * 1000)


class TraceEmitter(ABC):
    """Abstract interface for trace emission.

    Implementations can write to:
    - In-memory buffer (dev tools)
    - WebSocket (dev environment observer)
    - File (offline analysis)
    - Null (disabled)
    """

    @abstractmethod
    def emit(self, trace: DecisionTrace) -> None:
        """Emit a decision trace.

        Must be non-blocking. Implementations should handle
        their own buffering/async dispatch.
        """


class NullEmitter(TraceEmitter):
    """No-op emitter for when tracing is disabled."""

    def emit(self, trace: DecisionTrace) -> None:
        """Discard the trace."""


class BufferEmitter(TraceEmitter):
    """In-memory buffer for testing and dev tools.

    Stores traces in a bounded buffer (FIFO eviction).
    """

    def __init__(self, max_size: int = 1000) -> None:
        self._buffer: list[DecisionTrace] = []
        self._max_size = max_size

    def emit(self, trace: DecisionTrace) -> None:
        """Add trace to buffer, evicting oldest if full."""
        if len(self._buffer) >= self._max_size:
            self._buffer.pop(0)
        self._buffer.append(trace)

    @property
    def traces(self) -> list[DecisionTrace]:
        """Get all buffered traces."""
        return list(self._buffer)

    def clear(self) -> None:
        """Clear the buffer."""
        self._buffer.clear()

    def last(self, n: int = 1) -> list[DecisionTrace]:
        """Get the last N traces."""
        return self._buffer[-n:]


class CallbackEmitter(TraceEmitter):
    """Emitter that calls a callback function.

    Useful for WebSocket forwarding or custom handling.
    """

    def __init__(self, callback: Callable[[DecisionTrace], None]) -> None:
        self._callback = callback

    def emit(self, trace: DecisionTrace) -> None:
        """Call the callback with the trace."""
        self._callback(trace)


@dataclass
class TraceBuilder:
    """Builds a DecisionTrace during policy evaluation.

    Usage:
        builder = TraceBuilder(profile_id, trigger, snapshot)
        # During evaluation:
        builder.add_rule_evaluation(rule_id, result, ...)
        # After evaluation:
        builder.set_outcome(outcome_type, intent, ...)
        trace = builder.build()
    """

    profile_id: str
    profile_version: str | None
    home_id: str | None
    trigger: Trigger
    domain_snapshot: DomainSnapshot
    config: TraceConfig = field(default_factory=TraceConfig)

    # Timing (microseconds)
    _start_time_ns: int = field(default_factory=time.perf_counter_ns)
    _policy_start_ns: int = 0
    _policy_end_ns: int = 0

    # Accumulated data
    _rule_evaluations: list[RuleEvaluation] = field(default_factory=lambda: [])
    _quiet_hours: QuietHoursCheck | None = None
    _outcome: DecisionOutcome | None = None
    _decision_id: str | None = None
    _parent_decision_id: str | None = None

    def start_policy_evaluation(self) -> None:
        """Mark start of policy evaluation."""
        self._policy_start_ns = time.perf_counter_ns()

    def end_policy_evaluation(self) -> None:
        """Mark end of policy evaluation."""
        self._policy_end_ns = time.perf_counter_ns()

    def set_decision_id(self, decision_id: str, parent_id: str | None = None) -> None:
        """Set stable decision ID and optional parent for lineage."""
        self._decision_id = decision_id
        self._parent_decision_id = parent_id

    def add_rule_evaluation(
        self,
        rule_id: str,
        result: RuleResult,
        when_clause: ConditionCheck | None = None,
        additional_conditions: list[ConditionCheck] | None = None,
        suppress_if_checks: list[ConditionCheck] | None = None,
        failed_conditions: list[str] | None = None,
        classification: IntentClassification | None = None,
        skip_reason: str | None = None,
        suppress_reason: str | None = None,
    ) -> None:
        """Add a rule evaluation result."""
        self._rule_evaluations.append(
            RuleEvaluation(
                rule_id=rule_id,
                result=result,
                when_clause=when_clause,
                additional_conditions=additional_conditions or [],
                suppress_if_checks=suppress_if_checks or [],
                failed_conditions=failed_conditions or [],
                classification=classification,
                skip_reason=skip_reason,
                suppress_reason=suppress_reason,
            )
        )

    def set_quiet_hours(
        self,
        configured: bool,
        start_time: str | None = None,
        end_time: str | None = None,
        currently_active: bool = False,
        current_time: str | None = None,
    ) -> None:
        """Set quiet hours check result."""
        self._quiet_hours = QuietHoursCheck(
            configured=configured,
            start_time=start_time,
            end_time=end_time,
            currently_active=currently_active,
            current_time=current_time,
        )

    def set_outcome(
        self,
        outcome_type: OutcomeType,
        intent: WinningIntent | None = None,
        arbitration: ArbitrationTrace | None = None,
    ) -> None:
        """Set the final decision outcome."""
        self._outcome = DecisionOutcome(
            type=outcome_type,
            intent=intent,
            arbitration=arbitration,
        )

    def build(self) -> DecisionTrace:
        """Build the final trace."""
        end_time_ns = time.perf_counter_ns()

        # Calculate metrics
        metrics = None
        if self.config.include_metrics:
            total_us = (end_time_ns - self._start_time_ns) // 1000
            policy_us = 0
            if self._policy_end_ns > self._policy_start_ns:
                policy_us = (self._policy_end_ns - self._policy_start_ns) // 1000

            metrics = PerformanceMetrics(
                total_duration_us=total_us,
                policy_duration_us=policy_us,
                domains_evaluated=len(self.domain_snapshot.domains),
                rules_evaluated=len(self._rule_evaluations),
            )

        # Build policy trace
        matched = sum(
            1 for r in self._rule_evaluations if r.result == RuleResult.MATCHED
        )
        skipped = sum(
            1 for r in self._rule_evaluations if r.result == RuleResult.SKIPPED
        )

        policy_trace = PolicyEvaluationTrace(
            rules=self._rule_evaluations,
            quiet_hours=self._quiet_hours,
            rules_evaluated=len(self._rule_evaluations),
            rules_matched=matched,
            rules_skipped=skipped,
        )

        return DecisionTrace(
            trace_id=str(uuid4()),
            timestamp=datetime.now(),
            decision_id=self._decision_id,
            parent_decision_id=self._parent_decision_id,
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            home_id=self.home_id,
            trigger=self.trigger,
            domain_snapshot=self.domain_snapshot,
            policy_trace=policy_trace,
            outcome=self._outcome or DecisionOutcome(type=OutcomeType.NO_ACTION),
            metrics=metrics,
        )


# --- Helper functions for trace building ---


def build_trigger_from_state(
    updated_state: DomainState,
    previous_state: str | None = None,
) -> Trigger:
    """Build a Trigger from a domain state change."""
    return Trigger(
        type=TriggerType.STATE_CHANGE,
        domain=updated_state.domain,
        scope_id=updated_state.scope_id,
        previous_state=previous_state,
        new_state=updated_state.state,
        source=updated_state.metadata.get("entity_id"),
    )


def build_domain_snapshot(
    all_states: dict[str, DomainState],
    current_time: str,
) -> DomainSnapshot:
    """Build a DomainSnapshot from current domain states."""
    entries = [
        DomainStateEntry(
            domain=state.domain,
            state=state.state or "",
            scope_id=state.scope_id,
            metadata=state.metadata if state.metadata else None,
        )
        for state in all_states.values()
    ]

    return DomainSnapshot(
        domains=entries,
        snapshot_time=datetime.now(),
        time_of_day=current_time,
    )


def trace_rule_evaluation(
    rule: PolicyRule,
    state: DomainState,
    context: EvaluationContext,
    intent: IntentCandidate | None,
) -> RuleEvaluation:
    """Build a RuleEvaluation from a rule check.

    Captures the full reasoning chain including failed conditions.
    """
    # Check when clause (inline logic to avoid private import)
    when = rule.when
    when_satisfied = (
        when.domain == state.domain
        and (when.state is None or when.state == state.state)
        and (when.event is None or when.event == state.event)
    )
    when_clause = ConditionCheck(
        condition_type="when",
        domain=rule.when.domain,
        expected=rule.when.state or rule.when.event or "",
        actual=state.state or state.event or "",
        satisfied=when_satisfied,
    )

    # Collect failed conditions
    failed_conditions: list[str] = []
    additional_conditions: list[ConditionCheck] = []

    # Check additional conditions
    conditions_satisfied = True
    for domain_name, required_value in rule.conditions.items():
        domain_state = context.domain_states.get(domain_name)
        actual = domain_state.state if domain_state else None
        satisfied = actual == required_value

        additional_conditions.append(
            ConditionCheck(
                condition_type="condition",
                domain=domain_name,
                expected=required_value,
                actual=actual or "",
                satisfied=satisfied,
            )
        )

        if not satisfied:
            conditions_satisfied = False
            failed_conditions.append(f"{domain_name} == {required_value}")

    # Check suppress_if
    suppress_if_checks: list[ConditionCheck] = []

    for domain_name, suppress_value in rule.suppress_if.items():
        domain_state = context.domain_states.get(domain_name)
        actual = domain_state.state if domain_state else None
        triggered = actual == suppress_value

        suppress_if_checks.append(
            ConditionCheck(
                condition_type="suppress_if",
                domain=domain_name,
                expected=suppress_value,
                actual=actual or "",
                satisfied=triggered,
            )
        )

    # Determine result
    if not when_satisfied:
        result = RuleResult.SKIPPED
        skip_reason = f"when clause not satisfied: {rule.when.domain}"
        failed_conditions.insert(
            0, f"{rule.when.domain} == {rule.when.state or rule.when.event}"
        )
    elif not conditions_satisfied:
        result = RuleResult.SKIPPED
        skip_reason = "additional conditions not satisfied"
    elif intent is not None and intent.suppressed:
        result = RuleResult.SUPPRESSED
        skip_reason = None
    elif intent is not None:
        result = RuleResult.MATCHED
        skip_reason = None
    else:
        result = RuleResult.SKIPPED
        skip_reason = "no classification"

    # Build classification if rule has one
    classification = None
    if rule.classify:
        classification = IntentClassification(
            importance=rule.classify.importance,
            interrupt=rule.classify.interrupt,
            bypass_quiet_hours=rule.classify.bypass_quiet_hours,
        )

    return RuleEvaluation(
        rule_id=rule.rule_id,
        result=result,
        when_clause=when_clause,
        additional_conditions=additional_conditions,
        suppress_if_checks=suppress_if_checks,
        failed_conditions=failed_conditions if result == RuleResult.SKIPPED else [],
        classification=classification,
        skip_reason=skip_reason,
        suppress_reason=intent.suppression_reason
        if intent and intent.suppressed
        else None,
    )


def determine_outcome(
    intents: list[IntentCandidate],
) -> tuple[OutcomeType, WinningIntent | None]:
    """Determine the outcome type and winning intent from candidates."""
    if not intents:
        return OutcomeType.NO_ACTION, None

    # Find non-suppressed intents
    active = [i for i in intents if not i.suppressed]

    if not active:
        # All suppressed
        return OutcomeType.SUPPRESSED, None

    # Pick highest importance (simple arbitration)
    winner = max(
        active,
        key=lambda i: (
            [
                Importance.LOW,
                Importance.MEDIUM,
                Importance.HIGH,
                Importance.CRITICAL,
            ].index(i.importance),
            i.interrupt,
        ),
    )

    return OutcomeType.INTENT_GENERATED, WinningIntent(
        domain=winner.domain,
        rule_id=winner.rule_id,
        importance=winner.importance.value,
        interrupt=winner.interrupt,
        scope_id=winner.scope_id,
    )
