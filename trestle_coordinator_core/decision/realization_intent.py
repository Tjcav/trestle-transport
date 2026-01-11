"""Attention → Realization Mapping (Slice 7c).

This module answers one question:
"Given an attention level, what concrete outputs should this device perform?"

It:
- Consumes AttentionLevel (from 7b)
- Emits realization intents (not UI, not HA calls)
- Is the final step before the ICD frame is sent

Properties:
- Pure, deterministic, no IO
- Device capabilities only FILTER, never decide
- Never downgrade attention level - only drop unsupported channels
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from .attention import AttentionLevel
from .selection import DeviceContext

# --------------------------------------------------------------------------
# Output Channel Types
# --------------------------------------------------------------------------


class OutputChannel(Enum):
    """Output modality for alert delivery.

    These are capabilities, not implementations.
    The device decides HOW to render each channel.
    """

    VISUAL = "visual"
    AUDIO = "audio"
    HAPTIC = "haptic"
    AMBIENT = "ambient"


# --------------------------------------------------------------------------
# Realization Intent
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RealizationIntent:
    """Abstract output intent for a single channel.

    This is still abstract - nothing here says HOW to draw, beep, vibrate.
    The device interprets these intents into concrete UI/audio/haptic actions.

    Attributes:
        channel: The output modality (VISUAL, AUDIO, HAPTIC, AMBIENT).
        intensity: Low/medium/high intensity level.
        persistent: Whether this output should persist until dismissed.
        interruptive: Whether this output should interrupt the user.
    """

    channel: OutputChannel
    intensity: Literal["low", "medium", "high"]
    persistent: bool = False
    interruptive: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to ICD-compatible dictionary."""
        return {
            "channel": self.channel.value,
            "intensity": self.intensity,
            "persistent": self.persistent,
            "interruptive": self.interruptive,
        }


# --------------------------------------------------------------------------
# Realization Profiles (Static Policy)
# --------------------------------------------------------------------------


# Static mapping from attention level to baseline intents.
# This is policy, not user-configurable (yet).
# Device capabilities filter these, never modify the attention level.

REALIZATION_PROFILES: Mapping[AttentionLevel, list[RealizationIntent]] = {
    # PASSIVE: Ambient only, low intensity, non-persistent
    AttentionLevel.PASSIVE: [
        RealizationIntent(
            channel=OutputChannel.AMBIENT,
            intensity="low",
            persistent=False,
            interruptive=False,
        ),
    ],
    # GLANCE: Visual only, low intensity, non-interruptive
    AttentionLevel.GLANCE: [
        RealizationIntent(
            channel=OutputChannel.VISUAL,
            intensity="low",
            persistent=False,
            interruptive=False,
        ),
    ],
    # NOTIFY: Visual (medium, persistent) + Audio (low, non-interruptive)
    AttentionLevel.NOTIFY: [
        RealizationIntent(
            channel=OutputChannel.VISUAL,
            intensity="medium",
            persistent=True,
            interruptive=False,
        ),
        RealizationIntent(
            channel=OutputChannel.AUDIO,
            intensity="low",
            persistent=False,
            interruptive=False,
        ),
    ],
    # INTERRUPT: Visual (high, interruptive) + Audio (medium) + Haptic (medium)
    AttentionLevel.INTERRUPT: [
        RealizationIntent(
            channel=OutputChannel.VISUAL,
            intensity="high",
            persistent=False,
            interruptive=True,
        ),
        RealizationIntent(
            channel=OutputChannel.AUDIO,
            intensity="medium",
            persistent=False,
            interruptive=True,
        ),
        RealizationIntent(
            channel=OutputChannel.HAPTIC,
            intensity="medium",
            persistent=False,
            interruptive=True,
        ),
    ],
    # CRITICAL: All channels, high intensity, interruptive, persistent
    AttentionLevel.CRITICAL: [
        RealizationIntent(
            channel=OutputChannel.VISUAL,
            intensity="high",
            persistent=True,
            interruptive=True,
        ),
        RealizationIntent(
            channel=OutputChannel.AUDIO,
            intensity="high",
            persistent=True,
            interruptive=True,
        ),
        RealizationIntent(
            channel=OutputChannel.HAPTIC,
            intensity="high",
            persistent=True,
            interruptive=True,
        ),
    ],
}


# --------------------------------------------------------------------------
# Core Realization Function
# --------------------------------------------------------------------------


def realize_attention(
    attention: AttentionLevel,
    device: DeviceContext,
) -> list[RealizationIntent]:
    """Map attention level to filtered realization intents.

    This function:
    - Looks up baseline intents for the attention level
    - Filters out intents for unsupported device channels
    - NEVER downgrades attention level, only drops channels

    Args:
        attention: The computed attention level from Slice 7b.
        device: Device context with capability signals.

    Returns:
        List of RealizationIntent objects the device should execute.
        May be empty if device supports none of the required channels.

    Properties:
        - Pure (no side effects)
        - Deterministic (same inputs → identical output)
        - No IO, no timing, no HA calls
    """
    # Get baseline intents for this attention level
    baseline = REALIZATION_PROFILES.get(attention, [])

    # Extract device capability signals
    signals = device.signals
    supports_audio = signals.get("supports_audio", True)
    supports_haptic = signals.get("supports_haptic", False)
    supports_ambient = signals.get("supports_ambient", False)
    # Visual is always assumed supported

    # Filter intents based on device capabilities
    filtered: list[RealizationIntent] = []
    for intent in baseline:
        if intent.channel == OutputChannel.AUDIO and not supports_audio:
            continue
        if intent.channel == OutputChannel.HAPTIC and not supports_haptic:
            continue
        if intent.channel == OutputChannel.AMBIENT and not supports_ambient:
            continue
        # VISUAL always passes through
        filtered.append(intent)

    return filtered


# --------------------------------------------------------------------------
# ICD Frame Production
# --------------------------------------------------------------------------


def produce_realization_frame(
    alert_id: str,
    attention: AttentionLevel,
    intents: list[RealizationIntent],
) -> dict[str, Any]:
    """Produce ICD-compliant realization frame.

    This is what devices consume over the wire.

    Args:
        alert_id: Unique identifier for the alert.
        attention: The attention level being realized.
        intents: Filtered realization intents.

    Returns:
        ICD-compliant dictionary ready for protobuf serialization.
    """
    return {
        "type": "alert_realization",
        "alert_id": alert_id,
        "attention": attention.name,
        "outputs": [intent.to_dict() for intent in intents],
    }
