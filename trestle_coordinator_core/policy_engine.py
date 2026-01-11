"""Policy evaluation engine (Slice 8d).

This module evaluates policy rules against domain state to produce
classified intents. It does NOT execute actions - it only classifies.

The output is intent candidates that feed into the existing alert pipeline.
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any

from .profile import (
    LoadedPolicy,
    LoadedProfile,
    PolicyEffects,
    PolicyRule,
    QuietHours,
)


class Importance(Enum):
    """Intent importance levels (ordered)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_string(cls, s: str) -> "Importance":
        """Parse importance from string."""
        return cls(s.lower())

    def __lt__(self, other: "Importance") -> bool:
        order = [
            Importance.LOW,
            Importance.MEDIUM,
            Importance.HIGH,
            Importance.CRITICAL,
        ]
        return order.index(self) < order.index(other)

    def __le__(self, other: "Importance") -> bool:
        return self == other or self < other


@dataclass(frozen=True)
class DomainState:
    """Current state of a domain.

    Attributes:
        domain: Domain name.
        state: Current state value (or None).
        event: Current event (or None, for event-driven domains).
        scope_id: Scope identifier (room_id for per_room, "house" for global).
        metadata: Additional domain-specific data.
    """

    domain: str
    state: str | None = None
    event: str | None = None
    scope_id: str = "house"
    metadata: dict[str, Any] = field(default_factory=lambda: {})


@dataclass(frozen=True)
class IntentCandidate:
    """A classified intent candidate ready for the alert pipeline.

    Attributes:
        domain: Source domain.
        rule_id: Policy rule that matched.
        importance: Classified importance level.
        interrupt: Whether this should interrupt.
        bypass_quiet_hours: Whether to bypass quiet hours.
        suppressed: Whether this intent is suppressed.
        suppression_reason: Why it was suppressed (if applicable).
        scope_id: Scope of the intent.
        timestamp: When the intent was created.
    """

    domain: str
    rule_id: str
    importance: Importance
    interrupt: bool = False
    bypass_quiet_hours: bool = False
    suppressed: bool = False
    suppression_reason: str | None = None
    scope_id: str = "house"
    timestamp: datetime = field(default_factory=lambda: datetime.now())


@dataclass
class EvaluationContext:
    """Context for policy evaluation.

    Attributes:
        domain_states: Current state of all domains.
        current_time: Current time for quiet hours check.
        active_effects: Currently active effects (e.g., suppress_below_importance).
    """

    domain_states: dict[str, DomainState]
    current_time: time
    active_effects: list[PolicyEffects] = field(default_factory=lambda: [])


def _matches_condition(rule: PolicyRule, state: DomainState) -> bool:
    """Check if a rule's 'when' clause matches the domain state."""
    when = rule.when

    # Domain must match
    if when.domain != state.domain:
        return False

    # State match (if specified)
    if when.state is not None and when.state != state.state:
        return False

    # Event match (if specified)
    return when.event is None or when.event == state.event


def _check_conditions(rule: PolicyRule, context: EvaluationContext) -> bool:
    """Check additional conditions (e.g., house_mode: home)."""
    for domain_name, required_value in rule.conditions.items():
        domain_state = context.domain_states.get(domain_name)
        if domain_state is None:
            return False
        if domain_state.state != required_value:
            return False
    return True


def _check_suppress_if(rule: PolicyRule, context: EvaluationContext) -> str | None:
    """Check suppress_if conditions, return suppression reason if suppressed."""
    for domain_name, suppress_value in rule.suppress_if.items():
        domain_state = context.domain_states.get(domain_name)
        if domain_state is not None and domain_state.state == suppress_value:
            return f"{domain_name}={suppress_value}"
    return None


def _check_quiet_hours(
    quiet_hours: QuietHours | None,
    current_time: time,
    bypass: bool,
) -> bool:
    """Check if quiet hours should suppress.

    Returns True if suppressed by quiet hours.
    """
    if quiet_hours is None:
        return False
    if bypass:
        return False
    return quiet_hours.is_active(current_time)


def _check_importance_suppression(
    importance: Importance,
    effects: list[PolicyEffects],
) -> str | None:
    """Check if active effects suppress this importance level.

    Returns suppression reason if suppressed.
    """
    for effect in effects:
        if effect.suppress_below_importance:
            threshold = Importance.from_string(effect.suppress_below_importance)
            if importance < threshold:
                return f"importance below {threshold.value}"
    return None


def evaluate_rule(
    rule: PolicyRule,
    state: DomainState,
    context: EvaluationContext,
    quiet_hours: QuietHours | None,
) -> IntentCandidate | None:
    """Evaluate a single rule against domain state.

    Returns IntentCandidate if rule matches, None otherwise.
    """
    # Check if rule matches the domain state
    if not _matches_condition(rule, state):
        return None

    # Check additional conditions
    if not _check_conditions(rule, context):
        return None

    # If no classification, this rule only applies effects
    if rule.classify is None:
        return None

    classification = rule.classify
    importance = Importance.from_string(classification.importance)

    # Check suppress_if conditions
    suppress_reason = _check_suppress_if(rule, context)
    if suppress_reason:
        return IntentCandidate(
            domain=state.domain,
            rule_id=rule.rule_id,
            importance=importance,
            interrupt=classification.interrupt,
            bypass_quiet_hours=classification.bypass_quiet_hours,
            suppressed=True,
            suppression_reason=suppress_reason,
            scope_id=state.scope_id,
        )

    # Check quiet hours suppression
    if _check_quiet_hours(
        quiet_hours, context.current_time, classification.bypass_quiet_hours
    ):
        return IntentCandidate(
            domain=state.domain,
            rule_id=rule.rule_id,
            importance=importance,
            interrupt=False,  # Quiet hours suppresses interrupt
            bypass_quiet_hours=classification.bypass_quiet_hours,
            suppressed=True,
            suppression_reason="quiet_hours",
            scope_id=state.scope_id,
        )

    # Check importance-based suppression from active effects
    importance_suppress = _check_importance_suppression(
        importance, context.active_effects
    )
    if importance_suppress:
        return IntentCandidate(
            domain=state.domain,
            rule_id=rule.rule_id,
            importance=importance,
            interrupt=False,
            bypass_quiet_hours=classification.bypass_quiet_hours,
            suppressed=True,
            suppression_reason=importance_suppress,
            scope_id=state.scope_id,
        )

    # Not suppressed - full intent
    return IntentCandidate(
        domain=state.domain,
        rule_id=rule.rule_id,
        importance=importance,
        interrupt=classification.interrupt,
        bypass_quiet_hours=classification.bypass_quiet_hours,
        suppressed=False,
        suppression_reason=None,
        scope_id=state.scope_id,
    )


def collect_active_effects(
    policy: LoadedPolicy,
    context: EvaluationContext,
) -> list[PolicyEffects]:
    """Collect all active effects from the current domain states.

    Some rules apply effects (like suppress_below_importance) based on
    current state, without generating intents themselves.
    """
    effects: list[PolicyEffects] = []

    for rule in policy.rules:
        if rule.effects is None:
            continue

        # Check if this rule's condition is met by any current state
        for state in context.domain_states.values():
            if _matches_condition(rule, state):
                effects.append(rule.effects)
                break  # Don't add same effect twice

    return effects


def evaluate_domain_update(
    profile: LoadedProfile,
    updated_state: DomainState,
    all_states: dict[str, DomainState],
    current_time: time,
) -> list[IntentCandidate]:
    """Evaluate policy rules when a domain state changes.

    Args:
        profile: Loaded profile with policy.
        updated_state: The domain state that just changed.
        all_states: Current state of all domains.
        current_time: Current time for quiet hours.

    Returns:
        List of intent candidates (may include suppressed ones for logging).
    """
    policy = profile.policy

    # Build evaluation context
    context = EvaluationContext(
        domain_states=all_states,
        current_time=current_time,
    )

    # Collect active effects first
    context.active_effects = collect_active_effects(policy, context)

    # Evaluate all rules against the updated state
    intents: list[IntentCandidate] = []

    for rule in policy.rules:
        intent = evaluate_rule(rule, updated_state, context, policy.quiet_hours)
        if intent is not None:
            intents.append(intent)

    return intents


def evaluate_all_states(
    profile: LoadedProfile,
    all_states: dict[str, DomainState],
    current_time: time,
) -> list[IntentCandidate]:
    """Evaluate policy rules against all current domain states.

    Useful for initial evaluation or periodic re-evaluation.
    """
    policy = profile.policy

    context = EvaluationContext(
        domain_states=all_states,
        current_time=current_time,
    )

    context.active_effects = collect_active_effects(policy, context)

    intents: list[IntentCandidate] = []

    for state in all_states.values():
        for rule in policy.rules:
            intent = evaluate_rule(rule, state, context, policy.quiet_hours)
            if intent is not None:
                intents.append(intent)

    return intents
