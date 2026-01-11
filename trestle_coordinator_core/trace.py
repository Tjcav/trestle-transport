"""Decision trace data classes for explainability.

This module provides Python dataclasses matching the trace.proto schema.
Used for building decision traces during policy evaluation.

Slice: 8i - Decision Tracing & Explainability
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class TriggerType(Enum):
    """What initiated a decision cycle."""

    UNKNOWN = "unknown"
    STATE_CHANGE = "state_change"
    EVENT = "event"
    PERIODIC = "periodic"
    MANUAL = "manual"


class RuleResult(Enum):
    """Result of evaluating a single rule."""

    UNKNOWN = "unknown"
    MATCHED = "matched"
    SKIPPED = "skipped"
    SUPPRESSED = "suppressed"


class OutcomeType(Enum):
    """Final decision outcome type."""

    NO_ACTION = "no_action"
    SUPPRESSED = "suppressed"
    INTENT_GENERATED = "intent_generated"
    ALERT_DELIVERED = "alert_delivered"


@dataclass
class SignalContribution:
    """A single signal's contribution to fusion."""

    signal_source: str
    weight: float
    signal_type: str | None = None
    decay_factor: float = 1.0
    last_seen: datetime | None = None


@dataclass
class FusionContribution:
    """How a domain state was derived from signals."""

    signals: list[SignalContribution] = field(default_factory=lambda: [])
    confidence: float = 1.0
    last_update: datetime | None = None


@dataclass
class DomainStateEntry:
    """A single domain's state at decision time."""

    domain: str
    state: str
    scope_id: str | None = None
    metadata: dict[str, Any] | None = None
    fusion: FusionContribution | None = None


@dataclass
class ActiveEffect:
    """An active effect modifying behavior."""

    source_rule_id: str
    effect_type: str
    effect_value: str | None = None


@dataclass
class Trigger:
    """What initiated this decision cycle."""

    type: TriggerType
    domain: str
    scope_id: str | None = None
    previous_state: str | None = None
    new_state: str | None = None
    event: str | None = None
    source: str | None = None


@dataclass
class DomainSnapshot:
    """All domain states at decision time."""

    domains: list[DomainStateEntry]
    snapshot_time: datetime
    time_of_day: str | None = None
    active_effects: list[ActiveEffect] = field(default_factory=lambda: [])


@dataclass
class ConditionCheck:
    """Result of checking a single condition."""

    condition_type: str  # "when", "condition", "suppress_if"
    satisfied: bool
    domain: str | None = None
    expected: str | None = None
    actual: str | None = None


@dataclass
class IntentClassification:
    """How an intent would be classified."""

    importance: str  # low, medium, high, critical
    interrupt: bool = False
    bypass_quiet_hours: bool = False


@dataclass
class RuleEvaluation:
    """Evaluation trace for a single rule.

    failed_conditions captures explicit no-match reasons, critical for
    answering "why didn't this fire?" - e.g., ["media_activity == playing"]
    """

    rule_id: str
    result: RuleResult
    when_clause: ConditionCheck | None = None
    additional_conditions: list[ConditionCheck] = field(default_factory=lambda: [])
    suppress_if_checks: list[ConditionCheck] = field(default_factory=lambda: [])
    failed_conditions: list[str] = field(
        default_factory=lambda: []
    )  # Explicit no-match reasons
    classification: IntentClassification | None = None
    skip_reason: str | None = None
    suppress_reason: str | None = None


@dataclass
class QuietHoursCheck:
    """Quiet hours evaluation state."""

    configured: bool
    start_time: str | None = None
    end_time: str | None = None
    currently_active: bool = False
    current_time: str | None = None


@dataclass
class PolicyEvaluationTrace:
    """Complete policy evaluation trace."""

    rules: list[RuleEvaluation] = field(default_factory=lambda: [])
    quiet_hours: QuietHoursCheck | None = None
    rules_evaluated: int = 0
    rules_matched: int = 0
    rules_skipped: int = 0


@dataclass
class WinningIntent:
    """The intent that was selected."""

    domain: str
    rule_id: str
    importance: str
    interrupt: bool = False
    scope_id: str | None = None


@dataclass
class CompetingIntent:
    """An intent that competed for selection."""

    rule_id: str
    importance: str
    interrupt: bool = False
    selected: bool = False
    rejection_reason: str | None = None


@dataclass
class ArbitrationTrace:
    """Trace of intent arbitration."""

    candidates: list[CompetingIntent] = field(default_factory=lambda: [])
    selection_reason: str | None = None


@dataclass
class PanelDelivery:
    """Panel delivery decision."""

    delivered: bool
    target_panels: list[str] = field(default_factory=lambda: [])
    audible: bool = False
    haptic: bool = False
    visual_urgency: str | None = None
    skip_reason: str | None = None


@dataclass
class DecisionOutcome:
    """Final decision outcome."""

    type: OutcomeType
    intent: WinningIntent | None = None
    arbitration: ArbitrationTrace | None = None
    delivery: PanelDelivery | None = None


@dataclass
class PerformanceMetrics:
    """Performance timing for the decision."""

    total_duration_us: int = 0
    fusion_duration_us: int = 0
    policy_duration_us: int = 0
    arbitration_duration_us: int = 0
    domains_evaluated: int = 0
    rules_evaluated: int = 0


@dataclass
class DecisionTrace:
    """Complete trace of a single decision cycle.

    This is the top-level trace object that captures:
    - What triggered the decision
    - What the world looked like at decision time
    - How each rule was evaluated
    - What outcome was reached and why

    decision_id is a stable, referenceable ID for:
    - Panel interactions ("acknowledge decision X")
    - Chaining (escalation, retries via parent_decision_id)
    - Cross-home aggregation and learning
    """

    trace_id: str
    timestamp: datetime
    profile_id: str
    trigger: Trigger
    domain_snapshot: DomainSnapshot
    policy_trace: PolicyEvaluationTrace
    outcome: DecisionOutcome
    decision_id: str | None = None  # Stable decision ID (deterministic)
    parent_decision_id: str | None = None  # Lineage: parent decision (escalation/retry)
    profile_version: str | None = None
    home_id: str | None = None
    metrics: PerformanceMetrics | None = None

    @classmethod
    def create(
        cls,
        profile_id: str,
        trigger: Trigger,
        domain_snapshot: DomainSnapshot,
    ) -> DecisionTrace:
        """Create a new trace with auto-generated ID and timestamp."""
        return cls(
            trace_id=str(uuid4()),
            timestamp=datetime.now(),
            profile_id=profile_id,
            trigger=trigger,
            domain_snapshot=domain_snapshot,
            policy_trace=PolicyEvaluationTrace(),
            outcome=DecisionOutcome(type=OutcomeType.NO_ACTION),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert trace to dictionary for JSON serialization."""
        result = _to_dict(self)
        if isinstance(result, dict):
            return dict(result)  # pyright: ignore[reportUnknownArgumentType]
        return {}


def _to_dict(obj: object) -> str | list[object] | dict[str, object] | object:
    """Recursively convert dataclasses to dicts."""
    if isinstance(obj, Enum):
        return str(obj.value)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, object] = {}
        for f in dataclasses.fields(obj):
            value = getattr(obj, f.name)
            if value is not None:
                result[f.name] = _to_dict(value)
        return result
    return obj
