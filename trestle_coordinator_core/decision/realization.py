"""Core decision logic for alert realization.

This module implements the "secret sauce" — the single decision point that
determines what should actually happen when an alert intent is triggered.

Flow:
    Alert intent
      → capability match
        → policy evaluation
          → realization decision
            → device output

All decisions are:
- Deterministic (same inputs → same outputs)
- Side-effect free until realization
- Unit-testable
- Traceable (debug mode explains every decision)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any


# Life-safety threshold: alerts at or above this priority bypass quiet hours.
LIFE_SAFETY_THRESHOLD = 150


# --------------------------------------------------------------------------
# Enums for Decision Outputs
# --------------------------------------------------------------------------


class RealizationMode(str, Enum):
    """How the alert should be presented.

    Maps to ICD alert presentation strategies per alert_interaction_specification.md.
    """

    FULLSCREEN = "fullscreen"  # Priority 100-199: fullscreen takeover
    BANNER = "banner"  # Priority 50-99: alert bar side panel
    NOTIFICATION_CENTER = "notification_center"  # Priority 10-49: brief + background
    BACKGROUND = "background"  # Priority 1-9: status rail icon only
    SUPPRESSED = "suppressed"  # Not shown at all


class SuppressionReason(str, Enum):
    """Why an alert was suppressed."""

    CAPABILITY_DISABLED = "capability_disabled"
    USER_PREFERENCE_NEVER = "user_preference_never"
    ALERT_PREFERENCE_DISABLED = "alert_preference_disabled"
    QUIET_HOURS = "quiet_hours"
    PRIORITY_BELOW_THRESHOLD = "priority_below_threshold"
    COOLDOWN_ACTIVE = "cooldown_active"
    DOMAIN_DISABLED = "domain_disabled"
    ROOM_DISABLED = "room_disabled"


class EscalationReason(str, Enum):
    """Why an alert was escalated to higher priority."""

    LIFE_SAFETY = "life_safety"
    REPEATED_TRIGGER = "repeated_trigger"
    ESCALATION_TIMEOUT = "escalation_timeout"


# --------------------------------------------------------------------------
# Decision Context (All Inputs)
# --------------------------------------------------------------------------


@dataclass
class DecisionContext:
    """All inputs required for a single alert realization decision.

    This is the complete context needed to determine what should happen.
    Everything the decision needs is captured here — no external lookups.
    """

    # Alert identity.
    alert_id: str
    capability_id: str
    domain: str

    # Alert content.
    title: str
    message: str

    # Priority and timing.
    base_priority: int  # 1-199 per alert_interaction_specification.md
    timestamp: datetime
    current_time: datetime

    # Location context.
    room_id: str | None = None

    # Capability state.
    capability_enabled: bool = True

    # User preferences.
    visibility_preference: str = "sometimes"  # always, sometimes, never
    alert_preference: str = "enabled"  # enabled, silent, disabled
    allow_interruptions: bool = True
    quiet_hours_preference: bool = False

    # Policy snapshot.
    policy_enabled: bool = True
    policy_base_priority: int = 50
    domain_policy: Mapping[str, Any] = field(default_factory=lambda: {})
    room_policy: Mapping[str, Any] = field(default_factory=lambda: {})
    quiet_hours_start: str | None = None  # "HH:MM" format
    quiet_hours_end: str | None = None  # "HH:MM" format

    # State for cooldown/dedup.
    last_triggered: datetime | None = None
    cooldown_seconds: int = 0

    # Escalation state.
    trigger_count: int = 0
    escalation_threshold: int = 3


# --------------------------------------------------------------------------
# Realization Result (Decision Output)
# --------------------------------------------------------------------------


@dataclass
class RealizationResult:
    """The outcome of an alert realization decision.

    This is what the system should actually do.
    """

    # Should the alert be shown at all?
    realized: bool

    # How should it be presented?
    mode: RealizationMode

    # Final computed priority (after boosts/adjustments).
    computed_priority: int

    # Severity for device rendering.
    severity: str = "info"  # info, warning, critical

    # Should this interrupt the user?
    interrupt: bool = False

    # Auto-expiry in seconds (0 = no expiry).
    expires_seconds: int = 0

    # Should this go to notification center if dismissed?
    notification_center_eligible: bool = True

    # Why was this decision made? (for trace mode).
    suppression_reasons: list[SuppressionReason] = field(default_factory=lambda: [])
    escalation_reasons: list[EscalationReason] = field(default_factory=lambda: [])

    # Final adjusted values for debugging.
    priority_adjustments: list[str] = field(default_factory=lambda: [])


# --------------------------------------------------------------------------
# Decision Trace (Developer Observability)
# --------------------------------------------------------------------------


@dataclass
class DecisionTrace:
    """Debug trace of a realization decision.

    Explains exactly why each decision was made.
    For developers only — not user-facing.
    """

    alert_id: str
    timestamp: str

    # Input summary.
    base_priority: int
    capability_enabled: bool
    visibility_preference: str
    alert_preference: str
    in_quiet_hours: bool

    # Decision steps (ordered).
    steps: list[str] = field(default_factory=lambda: [])

    # Final outcome.
    realized: bool = False
    mode: str = "suppressed"
    computed_priority: int = 0
    suppression_reasons: list[str] = field(default_factory=lambda: [])
    escalation_reasons: list[str] = field(default_factory=lambda: [])


# --------------------------------------------------------------------------
# Core Decision Logic
# --------------------------------------------------------------------------


def realize_alert(context: DecisionContext) -> RealizationResult:
    """Determine what should actually happen for an alert intent.

    This is the single decision point for alert realization.
    All policy + preference + capability logic converges here.

    Decision order (strict):
        1. Capability enabled?
        2. User visibility preference
        3. Alert preference
        4. Policy enabled?
        5. Domain/room disabled?
        6. Quiet hours
        7. Cooldown
        8. Priority computation
        9. Mode selection

    Args:
        context: Complete decision context.

    Returns:
        RealizationResult with what should happen.
    """
    suppression_reasons: list[SuppressionReason] = []
    escalation_reasons: list[EscalationReason] = []
    priority_adjustments: list[str] = []

    # Start with base priority from policy.
    computed_priority = context.policy_base_priority
    priority_adjustments.append(f"base: {computed_priority}")

    # Override with alert's own priority if provided.
    if context.base_priority > 0:
        computed_priority = context.base_priority
        priority_adjustments.append(f"alert_base: {computed_priority}")

    # Step 1: Capability enabled?
    if not context.capability_enabled:
        suppression_reasons.append(SuppressionReason.CAPABILITY_DISABLED)
        return _suppressed_result(
            computed_priority,
            suppression_reasons,
            escalation_reasons,
            priority_adjustments,
        )

    # Step 2: User visibility preference.
    if context.visibility_preference == "never":
        suppression_reasons.append(SuppressionReason.USER_PREFERENCE_NEVER)
        return _suppressed_result(
            computed_priority,
            suppression_reasons,
            escalation_reasons,
            priority_adjustments,
        )

    # Step 3: Alert preference.
    if context.alert_preference == "disabled":
        suppression_reasons.append(SuppressionReason.ALERT_PREFERENCE_DISABLED)
        return _suppressed_result(
            computed_priority,
            suppression_reasons,
            escalation_reasons,
            priority_adjustments,
        )

    # Step 4: Policy enabled?
    if not context.policy_enabled:
        suppression_reasons.append(SuppressionReason.DOMAIN_DISABLED)
        return _suppressed_result(
            computed_priority,
            suppression_reasons,
            escalation_reasons,
            priority_adjustments,
        )

    # Step 5: Domain/room disabled?
    if not context.domain_policy.get("enabled", True):
        suppression_reasons.append(SuppressionReason.DOMAIN_DISABLED)
        return _suppressed_result(
            computed_priority,
            suppression_reasons,
            escalation_reasons,
            priority_adjustments,
        )

    if context.room_id and not context.room_policy.get("enabled", True):
        suppression_reasons.append(SuppressionReason.ROOM_DISABLED)
        return _suppressed_result(
            computed_priority,
            suppression_reasons,
            escalation_reasons,
            priority_adjustments,
        )

    # Step 6: Apply priority boosts from policy.
    domain_boost = context.domain_policy.get("priority_boost", 0)
    if domain_boost:
        computed_priority = max(1, min(199, computed_priority + domain_boost))
        priority_adjustments.append(f"domain_boost: {domain_boost:+d}")

    room_boost = context.room_policy.get("priority_boost", 0)
    if room_boost:
        computed_priority = max(1, min(199, computed_priority + room_boost))
        priority_adjustments.append(f"room_boost: {room_boost:+d}")

    # Step 7: Quiet hours check (life-safety bypasses).
    is_life_safety = computed_priority >= LIFE_SAFETY_THRESHOLD
    in_quiet_hours = _is_in_quiet_hours(
        context.current_time,
        context.quiet_hours_start,
        context.quiet_hours_end,
    )

    if in_quiet_hours and not is_life_safety and context.quiet_hours_preference:
        # User has quiet hours enabled for this capability.
        suppression_reasons.append(SuppressionReason.QUIET_HOURS)
        return _suppressed_result(
            computed_priority,
            suppression_reasons,
            escalation_reasons,
            priority_adjustments,
        )

    if is_life_safety:
        escalation_reasons.append(EscalationReason.LIFE_SAFETY)
        priority_adjustments.append("life_safety_bypass")

    # Step 8: Cooldown check.
    cooldown = context.domain_policy.get("cooldown_seconds", context.cooldown_seconds)
    if cooldown > 0 and context.last_triggered:
        elapsed = (context.current_time - context.last_triggered).total_seconds()
        if elapsed < cooldown:
            suppression_reasons.append(SuppressionReason.COOLDOWN_ACTIVE)
            return _suppressed_result(
                computed_priority,
                suppression_reasons,
                escalation_reasons,
                priority_adjustments,
            )

    # Step 9: Escalation check (repeated triggers).
    if context.trigger_count >= context.escalation_threshold:
        # Boost priority for repeated triggers.
        escalation_boost = min(50, context.trigger_count * 10)
        computed_priority = min(199, computed_priority + escalation_boost)
        priority_adjustments.append(f"escalation: +{escalation_boost}")
        escalation_reasons.append(EscalationReason.REPEATED_TRIGGER)

    # Step 10: Determine mode based on priority.
    mode = _priority_to_mode(computed_priority)

    # Step 11: Determine severity.
    severity = _priority_to_severity(computed_priority)

    # Step 12: Determine interrupt behavior.
    # Interrupt only if allowed by user and priority warrants it.
    interrupt = (
        context.allow_interruptions
        and computed_priority >= 100  # High priority.
        and context.alert_preference != "silent"
    )

    # Step 13: Determine expiry.
    # Higher priority alerts persist longer.
    if computed_priority >= LIFE_SAFETY_THRESHOLD:
        expires_seconds = 0  # Never auto-expire life-safety.
    elif computed_priority >= 100:
        expires_seconds = 300  # 5 minutes.
    elif computed_priority >= 50:
        expires_seconds = 120  # 2 minutes.
    else:
        expires_seconds = 30  # 30 seconds for low priority.

    # Step 14: Build result.
    return RealizationResult(
        realized=True,
        mode=mode,
        computed_priority=computed_priority,
        severity=severity,
        interrupt=interrupt,
        expires_seconds=expires_seconds,
        notification_center_eligible=mode != RealizationMode.SUPPRESSED,
        suppression_reasons=suppression_reasons,
        escalation_reasons=escalation_reasons,
        priority_adjustments=priority_adjustments,
    )


# --------------------------------------------------------------------------
# Trace Function (Developer Observability)
# --------------------------------------------------------------------------


def trace_decision(context: DecisionContext) -> DecisionTrace:
    """Generate a detailed trace of how a decision was made.

    This is for developers to understand:
    - Why was this alert suppressed?
    - Why was this escalated?

    Args:
        context: The decision context.

    Returns:
        DecisionTrace with step-by-step explanation.
    """
    steps: list[str] = []
    suppression_reasons: list[str] = []
    escalation_reasons: list[str] = []

    # Determine quiet hours status first.
    in_quiet_hours = _is_in_quiet_hours(
        context.current_time,
        context.quiet_hours_start,
        context.quiet_hours_end,
    )

    # Run through decision steps.
    steps.append(f"1. Capability enabled: {context.capability_enabled}")
    if not context.capability_enabled:
        suppression_reasons.append("capability_disabled")
        return DecisionTrace(
            alert_id=context.alert_id,
            timestamp=context.current_time.isoformat(),
            base_priority=context.base_priority,
            capability_enabled=context.capability_enabled,
            visibility_preference=context.visibility_preference,
            alert_preference=context.alert_preference,
            in_quiet_hours=in_quiet_hours,
            steps=steps,
            realized=False,
            suppression_reasons=suppression_reasons,
        )

    steps.append(f"2. Visibility preference: {context.visibility_preference}")
    if context.visibility_preference == "never":
        suppression_reasons.append("user_preference_never")
        return DecisionTrace(
            alert_id=context.alert_id,
            timestamp=context.current_time.isoformat(),
            base_priority=context.base_priority,
            capability_enabled=context.capability_enabled,
            visibility_preference=context.visibility_preference,
            alert_preference=context.alert_preference,
            in_quiet_hours=in_quiet_hours,
            steps=steps,
            realized=False,
            suppression_reasons=suppression_reasons,
        )

    steps.append(f"3. Alert preference: {context.alert_preference}")
    if context.alert_preference == "disabled":
        suppression_reasons.append("alert_preference_disabled")
        return DecisionTrace(
            alert_id=context.alert_id,
            timestamp=context.current_time.isoformat(),
            base_priority=context.base_priority,
            capability_enabled=context.capability_enabled,
            visibility_preference=context.visibility_preference,
            alert_preference=context.alert_preference,
            in_quiet_hours=in_quiet_hours,
            steps=steps,
            realized=False,
            suppression_reasons=suppression_reasons,
        )

    steps.append(f"4. Policy enabled: {context.policy_enabled}")
    steps.append(f"5. Domain policy: {dict(context.domain_policy)}")
    steps.append(f"6. Room policy: {dict(context.room_policy)}")

    # Compute final priority.
    computed = context.base_priority or context.policy_base_priority
    domain_boost = context.domain_policy.get("priority_boost", 0)
    room_boost = context.room_policy.get("priority_boost", 0)
    computed = max(1, min(199, computed + domain_boost + room_boost))

    steps.append(
        f"7. Priority computation: base={context.base_priority}, "
        f"domain_boost={domain_boost}, room_boost={room_boost}, "
        f"computed={computed}"
    )

    is_life_safety = computed >= LIFE_SAFETY_THRESHOLD
    steps.append(f"8. Life-safety: {is_life_safety}")
    steps.append(f"9. In quiet hours: {in_quiet_hours}")

    if is_life_safety:
        escalation_reasons.append("life_safety")
        steps.append("   → Life-safety bypasses quiet hours")

    mode = _priority_to_mode(computed)
    steps.append(f"10. Mode selection: {mode.value}")

    return DecisionTrace(
        alert_id=context.alert_id,
        timestamp=context.current_time.isoformat(),
        base_priority=context.base_priority,
        capability_enabled=context.capability_enabled,
        visibility_preference=context.visibility_preference,
        alert_preference=context.alert_preference,
        in_quiet_hours=in_quiet_hours,
        steps=steps,
        realized=True,
        mode=mode.value,
        computed_priority=computed,
        suppression_reasons=suppression_reasons,
        escalation_reasons=escalation_reasons,
    )


# --------------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------------


def _suppressed_result(
    computed_priority: int,
    suppression_reasons: list[SuppressionReason],
    escalation_reasons: list[EscalationReason],
    priority_adjustments: list[str],
) -> RealizationResult:
    """Build a suppressed RealizationResult."""
    return RealizationResult(
        realized=False,
        mode=RealizationMode.SUPPRESSED,
        computed_priority=computed_priority,
        severity="info",
        interrupt=False,
        expires_seconds=0,
        notification_center_eligible=False,
        suppression_reasons=suppression_reasons,
        escalation_reasons=escalation_reasons,
        priority_adjustments=priority_adjustments,
    )


def _priority_to_mode(priority: int) -> RealizationMode:
    """Map priority to presentation mode per alert_interaction_specification.md."""
    if priority >= 100:
        return RealizationMode.FULLSCREEN
    if priority >= 50:
        return RealizationMode.BANNER
    if priority >= 10:
        return RealizationMode.NOTIFICATION_CENTER
    return RealizationMode.BACKGROUND


def _priority_to_severity(priority: int) -> str:
    """Map priority to severity level."""
    if priority >= LIFE_SAFETY_THRESHOLD:
        return "critical"
    if priority >= 100:
        return "warning"
    return "info"


def _is_in_quiet_hours(
    current_time: datetime,
    start: str | None,
    end: str | None,
) -> bool:
    """Check if current time is within quiet hours.

    Handles overnight ranges (e.g., 22:00-07:00).
    """
    if not start or not end:
        return False

    try:
        start_parts = start.split(":")
        end_parts = end.split(":")
        start_time = time(int(start_parts[0]), int(start_parts[1]))
        end_time = time(int(end_parts[0]), int(end_parts[1]))
    except (ValueError, IndexError):
        return False

    current = current_time.time()

    # Handle overnight range (e.g., 22:00 - 07:00).
    if start_time > end_time:
        # Quiet hours span midnight.
        return current >= start_time or current <= end_time

    # Normal range (e.g., 23:00 - 06:00 same day).
    return start_time <= current <= end_time
