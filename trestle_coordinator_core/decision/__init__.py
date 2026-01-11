"""Decision logic for Trestle coordinator.

This package contains pure decision logic with no I/O dependencies.
All functions are deterministic and side-effect free.

Components:
- attention: Attention/interruption model for alert delivery
- selection: Device selection for alert targeting
- realization: Alert realization decisions (suppress, escalate, mode)
- realization_intent: Attention → Realization mapping (Slice 7c)
- frames: ICD-compatible frame production
"""

from .attention import (
    INTERRUPT_THRESHOLD,
    PRIORITY_CRITICAL,
    PRIORITY_GLANCE,
    PRIORITY_INTERRUPT,
    PRIORITY_NOTIFY,
    AttentionContext,
    AttentionLevel,
    compute_attention_level,
    compute_attention_level_from_device,
)
from .frames import (
    AlertAction,
    AlertFrame,
    RealizationHints,
    produce_alert_frame,
)
from .realization import (
    LIFE_SAFETY_THRESHOLD,
    DecisionContext,
    DecisionTrace,
    EscalationReason,
    RealizationMode,
    RealizationResult,
    SuppressionReason,
    realize_alert,
    trace_decision,
)
from .realization_intent import (
    REALIZATION_PROFILES,
    OutputChannel,
    RealizationIntent,
    produce_realization_frame,
    realize_attention,
)
from .selection import (
    AlertTarget,
    DeviceCapabilities,
    DeviceContext,
    SelectionResult,
    select_device,
)

__all__ = [
    "INTERRUPT_THRESHOLD",
    "LIFE_SAFETY_THRESHOLD",
    "PRIORITY_CRITICAL",
    "PRIORITY_GLANCE",
    "PRIORITY_INTERRUPT",
    "PRIORITY_NOTIFY",
    "REALIZATION_PROFILES",
    "AlertAction",
    "AlertFrame",
    "AlertTarget",
    "AttentionContext",
    "AttentionLevel",
    "DecisionContext",
    "DecisionTrace",
    "DeviceCapabilities",
    "DeviceContext",
    "EscalationReason",
    "OutputChannel",
    "RealizationHints",
    "RealizationIntent",
    "RealizationMode",
    "RealizationResult",
    "SelectionResult",
    "SuppressionReason",
    "compute_attention_level",
    "compute_attention_level_from_device",
    "produce_alert_frame",
    "produce_realization_frame",
    "realize_alert",
    "realize_attention",
    "select_device",
    "trace_decision",
]
