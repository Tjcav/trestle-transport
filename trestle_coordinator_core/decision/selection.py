"""Device selection for alert targeting.

Selects the best single target device for a realized alert at runtime using:
- Eligibility (online, permitted)
- Context (room match)
- Recency (last interaction)
- Device signals (ambient light, proximity, etc.)

Key invariants:
- Pure function: no I/O, no side effects
- Deterministic: same inputs → same output
- Order-independent: input order does not affect result
- Signal-agnostic: works without signals
- Forward-compatible: new signals do not require refactors
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# Thresholds for ambient light scoring.
HIGH_LUX_THRESHOLD = 500.0
LOW_LUX_THRESHOLD = 50.0

# Recency threshold in seconds for "recent interaction".
RECENT_INTERACTION_SECONDS = 300.0  # 5 minutes.

# Signal-based score modifiers.
SCORE_HIGH_LUX_PENALTY = -10
SCORE_LOW_LUX_BOOST = 20
SCORE_PROXIMITY_ACTIVE = 30
SCORE_RECENTLY_ACTIVE = 40
SCORE_RECENT_INTERACTION = 50
SCORE_ROOM_MATCH = 100
SCORE_SAME_ROOM_FALLBACK = 25
SCORE_SCREEN_FACING = 20


# --------------------------------------------------------------------------
# Data Types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceContext:
    """Runtime context for a device during selection.

    Attributes:
        device_id: Unique identifier for the device.
        room: Room the device is in, if known.
        online: Whether the device is currently online/reachable.
        last_interaction_ts: Unix timestamp of last user interaction, or None.
        signals: Extensible signal bag with runtime hints.

    Signal semantics:
        Signals are DEVICE-OWNED DECLARATIONS, not host-derived state.
        Devices publish facts; Trestle provides judgment.

        Recognized signals (all device-emitted):
        - recently_active (bool): User interacted with device recently.
        - proximity_active (bool): Someone is near the device.
        - screen_facing (bool): Device likely being looked at.
        - ambient_lux (float): Ambient light level near device.
        - motion_recent (bool): Motion detected near device recently.

    Signal ownership model:
        - Devices own signal semantics (host never synthesizes).
        - Host ingests signals and forwards into DeviceContext.
        - Selection logic only consumes, never reinterprets.
        - This allows device firmware to evolve independently.

    Signal rules:
        - MAY be empty.
        - Missing signals MUST be treated as "unknown", not false.
        - Selection logic MUST NOT assume signal presence.
    """

    device_id: str
    room: str | None = None
    online: bool = True
    last_interaction_ts: float | None = None
    signals: Mapping[str, Any] = field(default_factory=lambda: {})


@dataclass(frozen=True)
class SelectionResult:
    """Result of device selection.

    Attributes:
        device_id: Selected device ID, or None if no device qualifies.
        score: Computed score for selected device.
        score_breakdown: Detailed breakdown of score components.
        candidates_evaluated: Number of devices that were scored.
    """

    device_id: str | None
    score: int = 0
    score_breakdown: Mapping[str, int] = field(default_factory=lambda: {})
    candidates_evaluated: int = 0


@dataclass(frozen=True)
class AlertTarget:
    """Alert targeting information for device selection.

    Attributes:
        room_id: Target room for the alert, if room-specific.
        required_capabilities: Capabilities the device must have.
        excluded_devices: Device IDs explicitly excluded.
    """

    room_id: str | None = None
    required_capabilities: frozenset[str] = field(default_factory=lambda: frozenset())
    excluded_devices: frozenset[str] = field(default_factory=lambda: frozenset())


@dataclass(frozen=True)
class DeviceCapabilities:
    """Device capabilities for eligibility checking.

    Attributes:
        device_id: Device this applies to.
        capabilities: Set of capability IDs the device supports.
        suppressed: Whether this device is suppressed from alerts.
    """

    device_id: str
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset())
    suppressed: bool = False


# --------------------------------------------------------------------------
# Selection Algorithm
# --------------------------------------------------------------------------


def select_device(
    target: AlertTarget,
    devices: Sequence[DeviceContext],
    capabilities: Mapping[str, DeviceCapabilities],
    current_time: float,
) -> SelectionResult:
    """Select the best single target device for an alert.

    This is a pure function with no side effects. It:
    1. Filters devices to eligible candidates only.
    2. Scores each candidate based on context and signals.
    3. Breaks ties deterministically.

    Args:
        target: Alert targeting information (room, required capabilities).
        devices: List of device contexts to consider.
        capabilities: Device capabilities indexed by device_id.
        current_time: Current Unix timestamp for recency calculations.

    Returns:
        SelectionResult with selected device_id, or None if no device qualifies.
    """
    # Step 1: Filter to eligible devices.
    eligible: list[tuple[DeviceContext, DeviceCapabilities]] = []

    for device in devices:
        # Must be online.
        if not device.online:
            continue

        # Must not be explicitly excluded.
        if device.device_id in target.excluded_devices:
            continue

        # Get device capabilities.
        caps = capabilities.get(device.device_id)
        if caps is None:
            # Unknown device - skip.
            continue

        # Device must not be suppressed.
        if caps.suppressed:
            continue

        # Device must have all required capabilities.
        if target.required_capabilities and not target.required_capabilities.issubset(
            caps.capabilities
        ):
            continue

        eligible.append((device, caps))

    if not eligible:
        return SelectionResult(device_id=None, candidates_evaluated=0)

    # Step 2: Score each eligible device.
    scored: list[tuple[DeviceContext, int, dict[str, int]]] = []

    for device, _caps in eligible:
        score, breakdown = _compute_device_score(device, target, current_time)
        scored.append((device, score, breakdown))

    # Step 3: Sort by score (descending), then deterministic tie-break.
    scored.sort(key=lambda x: (-x[1], _tie_break_key(x[0], current_time)))

    # Return the winner.
    winner, winner_score, breakdown = scored[0]
    return SelectionResult(
        device_id=winner.device_id,
        score=winner_score,
        score_breakdown=breakdown,
        candidates_evaluated=len(eligible),
    )


def _compute_device_score(
    device: DeviceContext,
    target: AlertTarget,
    current_time: float,
) -> tuple[int, dict[str, int]]:
    """Compute selection score for a device.

    Args:
        device: Device context to score.
        target: Alert targeting information.
        current_time: Current Unix timestamp.

    Returns:
        Tuple of (total_score, score_breakdown).
    """
    score = 0
    breakdown: dict[str, int] = {}

    # Base score: Room match.
    if target.room_id and device.room == target.room_id:
        score += SCORE_ROOM_MATCH
        breakdown["room_match"] = SCORE_ROOM_MATCH
    elif target.room_id and device.room:
        # Same-building fallback (device has a room but not the target room).
        score += SCORE_SAME_ROOM_FALLBACK
        breakdown["same_room_fallback"] = SCORE_SAME_ROOM_FALLBACK

    # Base score: Recent interaction.
    if device.last_interaction_ts is not None:
        elapsed = current_time - device.last_interaction_ts
        if 0 <= elapsed < RECENT_INTERACTION_SECONDS:
            score += SCORE_RECENT_INTERACTION
            breakdown["recent_interaction"] = SCORE_RECENT_INTERACTION

    # Signal-based modifiers.
    signal_score, signal_breakdown = _compute_signal_score(device.signals)
    score += signal_score
    breakdown.update(signal_breakdown)

    return score, breakdown


def _compute_signal_score(signals: Mapping[str, Any]) -> tuple[int, dict[str, int]]:
    """Compute score modifiers from device signals.

    Missing signals are treated as "unknown" and contribute nothing.
    Unknown signal keys are ignored.
    Wrong types are ignored (no crash).

    Args:
        signals: Signal map from device context.

    Returns:
        Tuple of (signal_score, signal_breakdown).
    """
    score = 0
    breakdown: dict[str, int] = {}

    # Recently active: +40 if True (device-declared user activity).
    recently_active = signals.get("recently_active")
    if recently_active is True:
        score += SCORE_RECENTLY_ACTIVE
        breakdown["recently_active"] = SCORE_RECENTLY_ACTIVE

    # Proximity active: +30 if True.
    proximity = signals.get("proximity_active")
    if proximity is True:
        score += SCORE_PROXIMITY_ACTIVE
        breakdown["proximity_active"] = SCORE_PROXIMITY_ACTIVE

    # Screen facing: +20 if True.
    screen_facing = signals.get("screen_facing")
    if screen_facing is True:
        score += SCORE_SCREEN_FACING
        breakdown["screen_facing"] = SCORE_SCREEN_FACING

    # Ambient light: boost or penalty based on thresholds.
    lux = signals.get("ambient_lux")
    if isinstance(lux, int | float):
        if lux < LOW_LUX_THRESHOLD:
            score += SCORE_LOW_LUX_BOOST
            breakdown["low_lux"] = SCORE_LOW_LUX_BOOST
        elif lux > HIGH_LUX_THRESHOLD:
            score += SCORE_HIGH_LUX_PENALTY
            breakdown["high_lux"] = SCORE_HIGH_LUX_PENALTY

    return score, breakdown


def _tie_break_key(device: DeviceContext, current_time: float) -> tuple[float, str]:
    """Generate a deterministic tie-break key.

    Tie-break order:
    1. Most recent interaction wins (smaller elapsed time = better).
    2. Stable ordering by device_id (alphabetical).

    Args:
        device: Device context.
        current_time: Current Unix timestamp.

    Returns:
        Tuple for sorting (elapsed_time, device_id).
    """
    if device.last_interaction_ts is not None:
        elapsed = current_time - device.last_interaction_ts
    else:
        # No interaction - sort last (large elapsed).
        elapsed = float("inf")

    return (elapsed, device.device_id)
