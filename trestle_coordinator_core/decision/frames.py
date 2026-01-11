"""Realization frame producer.

Produces ICD-compatible frames from RealizationResult.
Devices never see:
- Host entity IDs
- Raw events
- Policies
- Preferences

They only see: what to do now.

Maps to trestle.proto Alert message with RealizationHints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .realization import RealizationMode, RealizationResult

# --------------------------------------------------------------------------
# ICD-Compatible Frame Structures
# --------------------------------------------------------------------------


@dataclass
class RealizationHints:
    """Coordinator-provided hints for how device should present alert.

    Maps to proto RealizationHints message.
    """

    audible: bool = False
    haptic: bool = False
    visual_urgency: str = "AMBIENT"  # AMBIENT, ATTENTION, URGENT
    respect_dnd: bool = True
    display_summary: str | None = None


@dataclass
class AlertAction:
    """Action button for alert.

    Maps to proto AlertAction message.
    """

    action_id: str
    label: str
    is_destructive: bool = False


@dataclass
class AlertFrame:
    """ICD-compatible alert frame for device consumption.

    This is what devices receive. It contains no:
    - Host entity IDs
    - Raw events
    - Policy data
    - Preference data

    Only: what to do right now.

    Maps to proto Alert message.
    """

    alert_id: str
    profile_id: str
    style: str  # INFORMATIONAL, WARNING, CRITICAL
    title: str
    message: str
    actions: list[AlertAction] = field(default_factory=lambda: [])
    hints: RealizationHints = field(default_factory=RealizationHints)
    metadata: dict[str, Any] = field(default_factory=lambda: {})
    timestamp: str = ""  # ISO format

    # Internal fields (not sent to device).
    expires_seconds: int = 0
    notification_center_eligible: bool = True

    def to_proto_dict(self) -> dict[str, Any]:
        """Convert to protobuf-compatible dictionary.

        This is the format sent over the wire.
        """
        return {
            "alert_id": self.alert_id,
            "profile_id": self.profile_id,
            "style": self.style,
            "title": self.title,
            "message": self.message,
            "actions": [
                {
                    "action_id": a.action_id,
                    "label": a.label,
                    "is_destructive": a.is_destructive,
                }
                for a in self.actions
            ],
            "hints": {
                "audible": self.hints.audible,
                "haptic": self.hints.haptic,
                "visual_urgency": self.hints.visual_urgency,
                "respect_dnd": self.hints.respect_dnd,
                "display_summary": self.hints.display_summary or "",
            },
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


# --------------------------------------------------------------------------
# Frame Producer
# --------------------------------------------------------------------------


def produce_alert_frame(
    result: RealizationResult,
    *,
    alert_id: str,
    profile_id: str,
    title: str,
    message: str,
    timestamp: str,
    actions: list[AlertAction] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AlertFrame | None:
    """Produce an ICD-compatible alert frame from a realization result.

    If the alert was suppressed, returns None.

    Args:
        result: The realization decision result.
        alert_id: Unique identifier for this alert.
        profile_id: Profile ID for routing.
        title: Alert title.
        message: Alert message.
        timestamp: ISO format timestamp.
        actions: Optional list of action buttons.
        metadata: Optional additional data.

    Returns:
        AlertFrame ready for device, or None if suppressed.
    """
    if not result.realized:
        return None

    # Map severity to proto AlertStyle.
    style = _severity_to_style(result.severity)

    # Build realization hints based on decision.
    hints = _build_hints(result)

    return AlertFrame(
        alert_id=alert_id,
        profile_id=profile_id,
        style=style,
        title=title,
        message=message,
        actions=actions or [],
        hints=hints,
        metadata=metadata or {},
        timestamp=timestamp,
        expires_seconds=result.expires_seconds,
        notification_center_eligible=result.notification_center_eligible,
    )


# --------------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------------


def _severity_to_style(severity: str) -> str:
    """Map severity to proto AlertStyle enum value."""
    if severity == "critical":
        return "CRITICAL"
    if severity == "warning":
        return "WARNING"
    return "INFORMATIONAL"


def _build_hints(result: RealizationResult) -> RealizationHints:
    """Build RealizationHints from RealizationResult."""
    # Determine visual urgency from mode.
    if result.mode == RealizationMode.FULLSCREEN:
        visual_urgency = "URGENT"
        audible = result.interrupt
        haptic = result.interrupt
    elif result.mode == RealizationMode.BANNER:
        visual_urgency = "ATTENTION"
        audible = result.interrupt
        haptic = False
    else:
        visual_urgency = "AMBIENT"
        audible = False
        haptic = False

    # Respect DND unless life-safety.
    respect_dnd = result.severity != "critical"

    return RealizationHints(
        audible=audible,
        haptic=haptic,
        visual_urgency=visual_urgency,
        respect_dnd=respect_dnd,
        display_summary=None,  # Coordinator may populate later.
    )
