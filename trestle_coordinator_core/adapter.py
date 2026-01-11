"""Ecosystem Adapter Boundary.

This module defines the canonical interface between Trestle core logic
and ecosystem adapters (Home Assistant, or any future ecosystem).

Key principles:
- Core logic is ecosystem-agnostic
- Home Assistant is ONE adapter, not THE architecture
- All adapter communication uses canonical models only
- Adapters perform translation only, never arbitration

Invariants (REQ-ARCH-ADAPT-xxx):
- REQ-ARCH-ADAPT-001: Core logic must not import HA modules
- REQ-ARCH-ADAPT-002: No ecosystem identifiers cross into canonical state
- REQ-ARCH-ADAPT-003: Adapters perform translation only, no arbitration
- REQ-ARCH-ADAPT-004: Core decisions are identical regardless of adapter source
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

# --------------------------------------------------------------------------
# Adapter Health
# --------------------------------------------------------------------------


class AdapterHealth(Enum):
    """Health status of an ecosystem adapter.

    Core uses this to:
    - Reduce confidence in adapter-sourced facts
    - Suppress aggressive behavior when degraded
    - Surface degraded state to UI

    Health is INPUT to core, never decision-making.
    """

    OK = "ok"
    DEGRADED = "degraded"
    OFFLINE = "offline"


# --------------------------------------------------------------------------
# Canonical Fact Types
# --------------------------------------------------------------------------


class FactType(Enum):
    """Types of facts that flow INTO core from adapters.

    These are ecosystem-agnostic observations about the world.
    Adapters translate their native events into these types.
    """

    # Presence and motion
    PRESENCE = "presence"
    MOTION = "motion"

    # Contact and security
    CONTACT = "contact"

    # Media state
    MEDIA_STATE = "media_state"

    # Environment
    ENVIRONMENT = "environment"

    # Device context signals (from 7a)
    DEVICE_CONTEXT = "device_context"

    # Health/connectivity
    ADAPTER_HEALTH = "adapter_health"


@dataclass(frozen=True)
class CanonicalFact:
    """A fact flowing from an ecosystem adapter into core.

    Facts are observations, not commands. They describe the current
    state of the world as observed by the adapter.

    Attributes:
        fact_type: The category of fact.
        source_id: Canonical identifier (NOT ecosystem-specific).
        timestamp: When the fact was observed.
        data: Fact-specific payload (schema varies by type).
        confidence: How confident the adapter is (0.0-1.0).
    """

    fact_type: FactType
    source_id: str
    timestamp: datetime
    data: Mapping[str, Any] = field(default_factory=lambda: {})
    confidence: float = 1.0

    def __post_init__(self) -> None:
        """Validate fact invariants."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")


# --------------------------------------------------------------------------
# Canonical Intent Types
# --------------------------------------------------------------------------


class IntentType(Enum):
    """Types of intents that flow OUT of core to adapters.

    These are ecosystem-agnostic commands for the adapter to execute.
    Adapters translate these into their native service calls.
    """

    # Display intents
    SHOW = "show"
    HIDE = "hide"
    UPDATE = "update"

    # Notification intents
    NOTIFY = "notify"
    INTERRUPT = "interrupt"

    # Alert lifecycle
    ESCALATE = "escalate"
    ACKNOWLEDGE = "acknowledge"
    SILENCE = "silence"
    DISMISS = "dismiss"

    # Device control
    ACTIVATE_OUTPUT = "activate_output"
    DEACTIVATE_OUTPUT = "deactivate_output"


@dataclass(frozen=True)
class CanonicalIntent:
    """An intent flowing from core to an ecosystem adapter.

    Intents are commands, not observations. They tell the adapter
    what to do without specifying how (ecosystem-specific).

    Attributes:
        intent_type: The category of intent.
        target_id: Canonical target identifier (NOT ecosystem-specific).
        timestamp: When the intent was created.
        data: Intent-specific payload (schema varies by type).
        priority: Urgency of execution (higher = more urgent).
        idempotency_key: For deduplication if needed.
    """

    intent_type: IntentType
    target_id: str
    timestamp: datetime
    data: Mapping[str, Any] = field(default_factory=lambda: {})
    priority: int = 50
    idempotency_key: str | None = None


# --------------------------------------------------------------------------
# Adapter Interface
# --------------------------------------------------------------------------


class FactSink(Protocol):
    """Protocol for receiving facts from an adapter.

    Core provides a sink; adapters push facts into it.
    This decouples the adapter from core's internal structure.
    """

    def receive_fact(self, fact: CanonicalFact) -> None:
        """Receive a fact from the adapter.

        Args:
            fact: The canonical fact to process.
        """
        ...


class EcosystemAdapter(ABC):
    """Abstract interface for ecosystem adapters.

    All ecosystems (Home Assistant, future platforms) must implement
    this interface to integrate with Trestle core.

    Adapters are responsible for:
    - Translating native events → canonical facts
    - Translating canonical intents → native service calls
    - Reporting their own health status
    - Owning ALL ecosystem-specific concerns

    Adapters must NOT:
    - Perform priority arbitration
    - Make alert gating decisions
    - Implement attention logic
    - Modify or filter intents based on policy
    """

    @abstractmethod
    def get_health(self) -> AdapterHealth:
        """Return current adapter health status.

        Returns:
            Current health (OK, DEGRADED, or OFFLINE).
        """
        ...

    @abstractmethod
    def subscribe_facts(
        self,
        sink: FactSink,
        fact_types: frozenset[FactType] | None = None,
    ) -> Callable[[], None]:
        """Subscribe to facts from this adapter.

        Args:
            sink: Where to send facts.
            fact_types: Optional filter for specific fact types.
                If None, receive all facts.

        Returns:
            Unsubscribe callable. Call to stop receiving facts.
        """
        ...

    @abstractmethod
    def apply_intent(self, intent: CanonicalIntent) -> None:
        """Apply an intent to the ecosystem.

        The adapter translates this canonical intent into
        ecosystem-specific actions (e.g., HA service calls).

        Args:
            intent: The intent to apply.

        Raises:
            AdapterError: If the intent cannot be applied.
        """
        ...

    @abstractmethod
    def get_adapter_id(self) -> str:
        """Return unique identifier for this adapter instance.

        Returns:
            Stable identifier string.
        """
        ...


# --------------------------------------------------------------------------
# Adapter Errors
# --------------------------------------------------------------------------


class AdapterError(Exception):
    """Base exception for adapter errors."""

    pass


class AdapterTranslationError(AdapterError):
    """Error translating between canonical and ecosystem types."""

    pass


class AdapterConnectionError(AdapterError):
    """Error connecting to the ecosystem."""

    pass


class AdapterIntentError(AdapterError):
    """Error applying an intent to the ecosystem."""

    pass


# --------------------------------------------------------------------------
# Fact Schemas (for validation)
# --------------------------------------------------------------------------

# These define the expected structure of fact.data for each FactType.
# Adapters should produce facts matching these schemas.
# Core may validate incoming facts against these.

FACT_SCHEMAS: Mapping[FactType, Mapping[str, type]] = {
    FactType.PRESENCE: {
        "present": bool,
        "zone_id": str,  # Optional
    },
    FactType.MOTION: {
        "detected": bool,
        "area_id": str,  # Optional
    },
    FactType.CONTACT: {
        "open": bool,
    },
    FactType.MEDIA_STATE: {
        "state": str,  # playing, paused, idle, off
        "media_type": str,  # Optional
    },
    FactType.ENVIRONMENT: {
        "temperature": float,  # Optional
        "humidity": float,  # Optional
        "illuminance": float,  # Optional (lux)
    },
    FactType.DEVICE_CONTEXT: {
        "device_id": str,
        "room": str,  # Optional
        "online": bool,
        "signals": dict,  # Dynamic signals from 7a
    },
    FactType.ADAPTER_HEALTH: {
        "status": str,  # ok, degraded, offline
        "reason": str,  # Optional
    },
}


# --------------------------------------------------------------------------
# Intent Schemas (for validation)
# --------------------------------------------------------------------------

# These define the expected structure of intent.data for each IntentType.
# Core produces intents matching these schemas.
# Adapters should handle these structures.

INTENT_SCHEMAS: Mapping[IntentType, Mapping[str, type]] = {
    IntentType.SHOW: {
        "content_type": str,
        "content_id": str,
        "priority": int,  # Optional
    },
    IntentType.HIDE: {
        "content_id": str,
    },
    IntentType.UPDATE: {
        "content_id": str,
        "changes": dict,
    },
    IntentType.NOTIFY: {
        "alert_id": str,
        "title": str,
        "message": str,
        "style": str,
    },
    IntentType.INTERRUPT: {
        "alert_id": str,
        "attention_level": str,
        "outputs": list,
    },
    IntentType.ESCALATE: {
        "alert_id": str,
        "from_level": int,
        "to_level": int,
    },
    IntentType.ACKNOWLEDGE: {
        "alert_id": str,
        "acknowledged_by": str,  # Optional
    },
    IntentType.SILENCE: {
        "alert_id": str,
        "duration_seconds": int,  # Optional
    },
    IntentType.DISMISS: {
        "alert_id": str,
    },
    IntentType.ACTIVATE_OUTPUT: {
        "channel": str,  # visual, audio, haptic, ambient
        "intensity": str,  # low, medium, high
        "persistent": bool,
    },
    IntentType.DEACTIVATE_OUTPUT: {
        "channel": str,
    },
}
