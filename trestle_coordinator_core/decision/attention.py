"""Attention and interruption model for alert delivery.

This module answers: "Given an alert that is allowed and prioritized,
how intrusive should it be right now?"

This slice (7b) introduces a formal attention/interruption model that:
- Decides HOW an alert is delivered
- Does NOT decide WHETHER the alert exists (that's Slice 6)
- Does NOT decide what UI looks like (that's device-side)

Key properties:
- Pure, deterministic, testable
- No HA calls, no device assumptions
- O(1) computation, no timers, no I/O
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .selection import DeviceContext


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# Life-safety threshold: critical bypass (same as realization module).
LIFE_SAFETY_THRESHOLD = 150

# Interrupt threshold: below this, interruptions are suppressed during quiet hours.
INTERRUPT_THRESHOLD = 100

# Priority thresholds for base attention level mapping.
PRIORITY_CRITICAL = 150  # Same as LIFE_SAFETY_THRESHOLD
PRIORITY_INTERRUPT = 100
PRIORITY_NOTIFY = 50
PRIORITY_GLANCE = 20


# --------------------------------------------------------------------------
# Core Types
# --------------------------------------------------------------------------


class AttentionLevel(Enum):
    """How intrusive an alert should be.

    This is the ONLY output of the attention model.
    Ordered from least to most intrusive.
    """

    PASSIVE = auto()  # Background, ambient, no interruption
    GLANCE = auto()  # Visible if looking, no interruption
    NOTIFY = auto()  # Notification-style, dismissible
    INTERRUPT = auto()  # Interrupts current content
    CRITICAL = auto()  # Overrides everything (life safety)

    def __lt__(self, other: object) -> bool:
        """Enable comparison between attention levels."""
        if not isinstance(other, AttentionLevel):
            return NotImplemented
        return self.value < other.value

    def __le__(self, other: object) -> bool:
        """Enable comparison between attention levels."""
        if not isinstance(other, AttentionLevel):
            return NotImplemented
        return self.value <= other.value

    def __gt__(self, other: object) -> bool:
        """Enable comparison between attention levels."""
        if not isinstance(other, AttentionLevel):
            return NotImplemented
        return self.value > other.value

    def __ge__(self, other: object) -> bool:
        """Enable comparison between attention levels."""
        if not isinstance(other, AttentionLevel):
            return NotImplemented
        return self.value >= other.value


# Ordered list for escalation stepping.
_ATTENTION_ORDER = [
    AttentionLevel.PASSIVE,
    AttentionLevel.GLANCE,
    AttentionLevel.NOTIFY,
    AttentionLevel.INTERRUPT,
    AttentionLevel.CRITICAL,
]


@dataclass(frozen=True)
class AttentionContext:
    """All inputs for computing attention level.

    This is a pure data structure with no HA objects.
    All fields are primitives or simple enums.

    Attributes:
        alert_priority: Alert priority (1-199).
        alert_domain: Domain of the alert (e.g., "motion_detection").
        quiet_hours: Whether quiet hours are currently active.
        cooldown_active: Whether the alert is in cooldown period.
        escalation_level: Number of escalation steps (0 = none).
        device_present: Whether a user is detected near device.
        device_proximity_near: Whether user is in close proximity.
        device_supports_interruptions: Whether device can show interruptions.
        device_recently_active: Whether device was recently used.
    """

    # Alert properties
    alert_priority: int
    alert_domain: str = ""

    # Policy state
    quiet_hours: bool = False
    cooldown_active: bool = False
    escalation_level: int = 0

    # Device context (from DeviceContext signals)
    device_present: bool = True
    device_proximity_near: bool = False
    device_supports_interruptions: bool = True
    device_recently_active: bool = False


# --------------------------------------------------------------------------
# Core Decision Function
# --------------------------------------------------------------------------


def compute_attention_level(context: AttentionContext) -> AttentionLevel:
    """Compute the appropriate attention level for an alert.

    This is a pure, deterministic function with no side effects.
    It implements the formal attention/interruption model.

    Decision rules (in order):
    1. Critical bypass: priority >= LIFE_SAFETY_THRESHOLD → CRITICAL
    2. Cooldown suppression: cooldown_active and escalation_level == 0 → PASSIVE
    3. Base level from priority
    4. Escalation: each level increases attention by one step
    5. Device presence modulation: nearby device allows higher attention
    6. Ambient-only devices: cap at GLANCE if no interruption support
    7. Quiet hours gating: cap at NOTIFY unless critical

    Args:
        context: AttentionContext with all decision inputs.

    Returns:
        The computed AttentionLevel.
    """
    # Rule 1: Critical bypass - life safety always wins.
    if context.alert_priority >= LIFE_SAFETY_THRESHOLD:
        return AttentionLevel.CRITICAL

    # Rule 2: Cooldown suppression - suppress if in cooldown with no escalation.
    if context.cooldown_active and context.escalation_level == 0:
        return AttentionLevel.PASSIVE

    # Rule 3: Compute base attention level from priority.
    level = _base_attention_from_priority(context.alert_priority)

    # Rule 4: Apply escalation (each level increases by one step).
    level = _apply_escalation(level, context.escalation_level)

    # Rule 5: Device presence modulation.
    # If user is nearby and device was recently active, allow higher attention.
    if context.device_proximity_near and context.device_recently_active:
        level = _step_up(level)

    # Rule 6: Ambient-only devices cap at GLANCE.
    if not context.device_supports_interruptions:
        level = _cap_at(level, AttentionLevel.GLANCE)

    # Rule 7: Quiet hours gating - cap at NOTIFY unless critical.
    # (Critical already handled in Rule 1)
    if context.quiet_hours and level > AttentionLevel.NOTIFY:
        level = AttentionLevel.NOTIFY

    return level


def compute_attention_level_from_device(
    alert_priority: int,
    device: DeviceContext,
    *,
    alert_domain: str = "",
    quiet_hours: bool = False,
    cooldown_active: bool = False,
    escalation_level: int = 0,
) -> AttentionLevel:
    """Convenience function that extracts signals from DeviceContext.

    This bridges between the DeviceContext from Slice 7a and the
    AttentionContext needed for attention computation.

    Args:
        alert_priority: Alert priority (1-199).
        device: DeviceContext from device selection.
        alert_domain: Domain of the alert.
        quiet_hours: Whether quiet hours are active.
        cooldown_active: Whether alert is in cooldown.
        escalation_level: Current escalation level.

    Returns:
        The computed AttentionLevel.
    """
    signals = device.signals

    # Extract device signals with safe defaults.
    # Missing signals are treated as "unknown" (conservative defaults).
    device_present = bool(signals.get("proximity_active", True))
    device_proximity_near = bool(signals.get("proximity_active", False))
    device_supports_interruptions = bool(signals.get("supports_interruptions", True))
    device_recently_active = bool(signals.get("recently_active", False))

    context = AttentionContext(
        alert_priority=alert_priority,
        alert_domain=alert_domain,
        quiet_hours=quiet_hours,
        cooldown_active=cooldown_active,
        escalation_level=escalation_level,
        device_present=device_present,
        device_proximity_near=device_proximity_near,
        device_supports_interruptions=device_supports_interruptions,
        device_recently_active=device_recently_active,
    )

    return compute_attention_level(context)


# --------------------------------------------------------------------------
# Helper Functions (Private)
# --------------------------------------------------------------------------


def _base_attention_from_priority(priority: int) -> AttentionLevel:
    """Map priority to base attention level.

    Priority ranges:
    - 150+: CRITICAL (handled separately via life-safety bypass)
    - 100-149: INTERRUPT
    - 50-99: NOTIFY
    - 20-49: GLANCE
    - 1-19: PASSIVE
    """
    if priority >= PRIORITY_CRITICAL:
        return AttentionLevel.CRITICAL
    if priority >= PRIORITY_INTERRUPT:
        return AttentionLevel.INTERRUPT
    if priority >= PRIORITY_NOTIFY:
        return AttentionLevel.NOTIFY
    if priority >= PRIORITY_GLANCE:
        return AttentionLevel.GLANCE
    return AttentionLevel.PASSIVE


def _apply_escalation(level: AttentionLevel, escalation_level: int) -> AttentionLevel:
    """Apply escalation steps to attention level.

    Each escalation level increases attention by one step, up to CRITICAL.
    """
    if escalation_level <= 0:
        return level

    current_idx = _ATTENTION_ORDER.index(level)
    new_idx = min(current_idx + escalation_level, len(_ATTENTION_ORDER) - 1)
    return _ATTENTION_ORDER[new_idx]


def _step_up(level: AttentionLevel) -> AttentionLevel:
    """Increase attention level by one step (max CRITICAL)."""
    current_idx = _ATTENTION_ORDER.index(level)
    new_idx = min(current_idx + 1, len(_ATTENTION_ORDER) - 1)
    return _ATTENTION_ORDER[new_idx]


def _cap_at(level: AttentionLevel, cap: AttentionLevel) -> AttentionLevel:
    """Cap attention level at a maximum."""
    if level > cap:
        return cap
    return level
