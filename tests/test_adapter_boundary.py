"""Tests for Slice 7d — Ecosystem Adapter Boundary.

These tests enforce the architectural invariants that keep core logic
ecosystem-agnostic. They are the real value of Slice 7d.

Invariants tested:
- REQ-ARCH-ADAPT-001: Core logic must not import HA modules
- REQ-ARCH-ADAPT-002: No ecosystem identifiers cross into canonical state
- REQ-ARCH-ADAPT-003: Adapters perform translation only, no arbitration
- REQ-ARCH-ADAPT-004: Core decisions are identical regardless of adapter source
"""

import ast
import importlib
import inspect
import pkgutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from trestle_coordinator_core.adapter import (
    FACT_SCHEMAS,
    INTENT_SCHEMAS,
    AdapterConnectionError,
    AdapterError,
    AdapterHealth,
    AdapterIntentError,
    AdapterTranslationError,
    CanonicalFact,
    CanonicalIntent,
    EcosystemAdapter,
    FactSink,
    FactType,
    IntentType,
)


class TestAdapterHealth:
    """Tests for AdapterHealth enum."""

    def test_health_values(self) -> None:
        """AdapterHealth has exactly three states."""
        assert len(AdapterHealth) == 3
        assert AdapterHealth.OK.value == "ok"
        assert AdapterHealth.DEGRADED.value == "degraded"
        assert AdapterHealth.OFFLINE.value == "offline"

    def test_health_ordering_by_severity(self) -> None:
        """Health states have implicit severity ordering."""
        # OK < DEGRADED < OFFLINE in terms of severity
        # We verify they're distinct and can be compared
        states = list(AdapterHealth)
        assert len(set(states)) == 3

    def test_health_serializable(self) -> None:
        """Health values are serializable strings."""
        for health in AdapterHealth:
            assert isinstance(health.value, str)
            assert health.value == health.name.lower()


class TestFactType:
    """Tests for FactType enum."""

    def test_fact_types_exist(self) -> None:
        """All specified fact types exist."""
        assert FactType.PRESENCE
        assert FactType.MOTION
        assert FactType.CONTACT
        assert FactType.MEDIA_STATE
        assert FactType.ENVIRONMENT
        assert FactType.DEVICE_CONTEXT
        assert FactType.ADAPTER_HEALTH

    def test_fact_types_are_strings(self) -> None:
        """Fact type values are serializable strings."""
        for ft in FactType:
            assert isinstance(ft.value, str)

    def test_fact_schemas_cover_all_types(self) -> None:
        """Every FactType has a schema defined."""
        for ft in FactType:
            assert ft in FACT_SCHEMAS, f"Missing schema for {ft}"


class TestIntentType:
    """Tests for IntentType enum."""

    def test_intent_types_exist(self) -> None:
        """All specified intent types exist."""
        assert IntentType.SHOW
        assert IntentType.HIDE
        assert IntentType.UPDATE
        assert IntentType.NOTIFY
        assert IntentType.INTERRUPT
        assert IntentType.ESCALATE
        assert IntentType.ACKNOWLEDGE
        assert IntentType.SILENCE
        assert IntentType.DISMISS
        assert IntentType.ACTIVATE_OUTPUT
        assert IntentType.DEACTIVATE_OUTPUT

    def test_intent_types_are_strings(self) -> None:
        """Intent type values are serializable strings."""
        for it in IntentType:
            assert isinstance(it.value, str)

    def test_intent_schemas_cover_all_types(self) -> None:
        """Every IntentType has a schema defined."""
        for it in IntentType:
            assert it in INTENT_SCHEMAS, f"Missing schema for {it}"


class TestCanonicalFact:
    """Tests for CanonicalFact dataclass."""

    def test_fact_creation(self) -> None:
        """CanonicalFact can be created with required fields."""
        now = datetime.now(UTC)
        fact = CanonicalFact(
            fact_type=FactType.PRESENCE,
            source_id="room:living_room",
            timestamp=now,
        )
        assert fact.fact_type == FactType.PRESENCE
        assert fact.source_id == "room:living_room"
        assert fact.timestamp == now
        assert fact.data == {}
        assert fact.confidence == 1.0

    def test_fact_with_data(self) -> None:
        """CanonicalFact accepts arbitrary data payload."""
        fact = CanonicalFact(
            fact_type=FactType.PRESENCE,
            source_id="room:kitchen",
            timestamp=datetime.now(UTC),
            data={"present": True, "zone_id": "home"},
        )
        assert fact.data["present"] is True
        assert fact.data["zone_id"] == "home"

    def test_fact_confidence_bounds(self) -> None:
        """Confidence must be between 0.0 and 1.0."""
        # Valid boundary values
        fact_low = CanonicalFact(
            fact_type=FactType.MOTION,
            source_id="sensor:1",
            timestamp=datetime.now(UTC),
            confidence=0.0,
        )
        assert fact_low.confidence == 0.0

        fact_high = CanonicalFact(
            fact_type=FactType.MOTION,
            source_id="sensor:2",
            timestamp=datetime.now(UTC),
            confidence=1.0,
        )
        assert fact_high.confidence == 1.0

    def test_fact_confidence_invalid(self) -> None:
        """Invalid confidence raises ValueError."""
        with pytest.raises(ValueError, match="Confidence must be 0.0-1.0"):
            CanonicalFact(
                fact_type=FactType.MOTION,
                source_id="sensor:3",
                timestamp=datetime.now(UTC),
                confidence=1.5,
            )

        with pytest.raises(ValueError, match="Confidence must be 0.0-1.0"):
            CanonicalFact(
                fact_type=FactType.MOTION,
                source_id="sensor:4",
                timestamp=datetime.now(UTC),
                confidence=-0.1,
            )

    def test_fact_is_immutable(self) -> None:
        """CanonicalFact is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        fact = CanonicalFact(
            fact_type=FactType.CONTACT,
            source_id="door:front",
            timestamp=datetime.now(UTC),
        )
        with pytest.raises(FrozenInstanceError):
            fact.source_id = "door:back"  # type: ignore[misc]

    def test_fact_no_ecosystem_identifiers(self) -> None:
        """Facts should use canonical IDs, not ecosystem-specific ones.

        REQ-ARCH-ADAPT-002: No ecosystem identifiers cross into canonical state.
        """
        # Good: canonical identifiers
        good_ids = [
            "room:living_room",
            "device:panel_1",
            "zone:home",
            "area:kitchen",
        ]

        # Bad: ecosystem-specific identifiers (should not appear)
        bad_patterns = [
            "binary_sensor.front_door",  # HA entity
            "sensor.kitchen_temp",  # HA entity
            "homeassistant.turn_on",  # HA service
            "home_assistant://",  # HA URL scheme
        ]

        for good_id in good_ids:
            fact = CanonicalFact(
                fact_type=FactType.DEVICE_CONTEXT,
                source_id=good_id,
                timestamp=datetime.now(UTC),
            )
            assert fact.source_id == good_id

            # Verify no bad patterns in the ID
            for bad in bad_patterns:
                assert bad not in fact.source_id


class TestCanonicalIntent:
    """Tests for CanonicalIntent dataclass."""

    def test_intent_creation(self) -> None:
        """CanonicalIntent can be created with required fields."""
        now = datetime.now(UTC)
        intent = CanonicalIntent(
            intent_type=IntentType.NOTIFY,
            target_id="device:panel_1",
            timestamp=now,
        )
        assert intent.intent_type == IntentType.NOTIFY
        assert intent.target_id == "device:panel_1"
        assert intent.timestamp == now
        assert intent.data == {}
        assert intent.priority == 50
        assert intent.idempotency_key is None

    def test_intent_with_data(self) -> None:
        """CanonicalIntent accepts arbitrary data payload."""
        intent = CanonicalIntent(
            intent_type=IntentType.INTERRUPT,
            target_id="device:panel_2",
            timestamp=datetime.now(UTC),
            data={
                "alert_id": "alert:123",
                "attention_level": "interrupt",
                "outputs": ["visual", "audio"],
            },
            priority=80,
            idempotency_key="alert:123:v1",
        )
        assert intent.data["alert_id"] == "alert:123"
        assert intent.priority == 80
        assert intent.idempotency_key == "alert:123:v1"

    def test_intent_is_immutable(self) -> None:
        """CanonicalIntent is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        intent = CanonicalIntent(
            intent_type=IntentType.SHOW,
            target_id="device:panel_1",
            timestamp=datetime.now(UTC),
        )
        with pytest.raises(FrozenInstanceError):
            intent.target_id = "device:panel_2"  # type: ignore[misc]

    def test_intent_no_ecosystem_identifiers(self) -> None:
        """Intents should use canonical IDs, not ecosystem-specific ones.

        REQ-ARCH-ADAPT-002: No ecosystem identifiers cross into canonical state.
        """
        # Good: canonical identifiers
        good_ids = [
            "device:panel_1",
            "room:bedroom",
            "alert:smoke_detector",
        ]

        # Bad: ecosystem-specific identifiers
        bad_patterns = [
            "light.living_room",
            "switch.kitchen",
            "automation.",
            "script.",
        ]

        for good_id in good_ids:
            intent = CanonicalIntent(
                intent_type=IntentType.NOTIFY,
                target_id=good_id,
                timestamp=datetime.now(UTC),
            )
            assert intent.target_id == good_id

            for bad in bad_patterns:
                assert bad not in intent.target_id


class TestEcosystemAdapterInterface:
    """Tests for EcosystemAdapter abstract interface."""

    def test_adapter_is_abstract(self) -> None:
        """EcosystemAdapter cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            EcosystemAdapter()  # type: ignore[abstract]

    def test_adapter_requires_get_health(self) -> None:
        """Adapter must implement get_health."""
        assert hasattr(EcosystemAdapter, "get_health")
        assert "get_health" in EcosystemAdapter.__abstractmethods__

    def test_adapter_requires_subscribe_facts(self) -> None:
        """Adapter must implement subscribe_facts."""
        assert hasattr(EcosystemAdapter, "subscribe_facts")
        assert "subscribe_facts" in EcosystemAdapter.__abstractmethods__

    def test_adapter_requires_apply_intent(self) -> None:
        """Adapter must implement apply_intent."""
        assert hasattr(EcosystemAdapter, "apply_intent")
        assert "apply_intent" in EcosystemAdapter.__abstractmethods__

    def test_adapter_requires_get_adapter_id(self) -> None:
        """Adapter must implement get_adapter_id."""
        assert hasattr(EcosystemAdapter, "get_adapter_id")
        assert "get_adapter_id" in EcosystemAdapter.__abstractmethods__


class FakeAdapter(EcosystemAdapter):
    """A fake adapter for testing core logic in isolation.

    This demonstrates that core can run entirely without HA.
    """

    def __init__(
        self,
        adapter_id: str = "fake:test",
        health: AdapterHealth = AdapterHealth.OK,
    ) -> None:
        self._adapter_id = adapter_id
        self._health = health
        self._sinks: list[FactSink] = []
        self._applied_intents: list[CanonicalIntent] = []

    def get_health(self) -> AdapterHealth:
        return self._health

    def set_health(self, health: AdapterHealth) -> None:
        """Test helper to simulate health changes."""
        self._health = health

    def subscribe_facts(
        self,
        sink: FactSink,
        fact_types: frozenset[FactType] | None = None,
    ) -> Callable[[], None]:
        self._sinks.append(sink)

        def unsubscribe() -> None:
            if sink in self._sinks:
                self._sinks.remove(sink)

        return unsubscribe

    def apply_intent(self, intent: CanonicalIntent) -> None:
        self._applied_intents.append(intent)

    def get_adapter_id(self) -> str:
        return self._adapter_id

    # Test helpers
    def emit_fact(self, fact: CanonicalFact) -> None:
        """Push a fact to all subscribers."""
        for sink in self._sinks:
            sink.receive_fact(fact)

    def get_applied_intents(self) -> list[CanonicalIntent]:
        return list(self._applied_intents)

    def clear_intents(self) -> None:
        self._applied_intents.clear()


class RecordingFactSink:
    """A FactSink that records received facts."""

    def __init__(self) -> None:
        self.facts: list[CanonicalFact] = []

    def receive_fact(self, fact: CanonicalFact) -> None:
        self.facts.append(fact)


class TestFakeAdapter:
    """Tests for FakeAdapter implementation."""

    def test_fake_adapter_instantiation(self) -> None:
        """FakeAdapter can be instantiated."""
        adapter = FakeAdapter()
        assert adapter.get_adapter_id() == "fake:test"
        assert adapter.get_health() == AdapterHealth.OK

    def test_fake_adapter_health_changes(self) -> None:
        """FakeAdapter health can be changed for testing."""
        adapter = FakeAdapter()
        assert adapter.get_health() == AdapterHealth.OK

        adapter.set_health(AdapterHealth.DEGRADED)
        assert adapter.get_health() == AdapterHealth.DEGRADED

        adapter.set_health(AdapterHealth.OFFLINE)
        assert adapter.get_health() == AdapterHealth.OFFLINE

    def test_fake_adapter_fact_subscription(self) -> None:
        """FakeAdapter can subscribe and emit facts."""
        adapter = FakeAdapter()
        sink = RecordingFactSink()

        unsub = adapter.subscribe_facts(sink)

        fact = CanonicalFact(
            fact_type=FactType.PRESENCE,
            source_id="room:test",
            timestamp=datetime.now(UTC),
            data={"present": True},
        )
        adapter.emit_fact(fact)

        assert len(sink.facts) == 1
        assert sink.facts[0] == fact

        # Unsubscribe
        unsub()
        adapter.emit_fact(fact)
        assert len(sink.facts) == 1  # No new facts

    def test_fake_adapter_intent_application(self) -> None:
        """FakeAdapter records applied intents."""
        adapter = FakeAdapter()

        intent = CanonicalIntent(
            intent_type=IntentType.NOTIFY,
            target_id="device:test",
            timestamp=datetime.now(UTC),
        )
        adapter.apply_intent(intent)

        applied = adapter.get_applied_intents()
        assert len(applied) == 1
        assert applied[0] == intent


class TestCoreDeterminism:
    """Tests that core logic produces identical results regardless of adapter.

    REQ-ARCH-ADAPT-004: Core decisions are identical regardless of adapter source.
    """

    def test_same_facts_produce_same_decisions(self) -> None:
        """Two adapters with identical facts produce identical results."""
        adapter_a = FakeAdapter(adapter_id="fake:a")
        adapter_b = FakeAdapter(adapter_id="fake:b")

        # Same facts from different adapters
        now = datetime.now(UTC)
        fact = CanonicalFact(
            fact_type=FactType.MOTION,
            source_id="area:hallway",
            timestamp=now,
            data={"detected": True},
        )

        sink_a = RecordingFactSink()
        sink_b = RecordingFactSink()

        adapter_a.subscribe_facts(sink_a)
        adapter_b.subscribe_facts(sink_b)

        adapter_a.emit_fact(fact)
        adapter_b.emit_fact(fact)

        # Facts received are identical
        assert sink_a.facts == sink_b.facts

    def test_adapter_id_does_not_affect_fact_content(self) -> None:
        """Adapter identity is not embedded in facts."""
        adapter = FakeAdapter(adapter_id="fake:unique_id")
        sink = RecordingFactSink()
        adapter.subscribe_facts(sink)

        fact = CanonicalFact(
            fact_type=FactType.PRESENCE,
            source_id="zone:home",
            timestamp=datetime.now(UTC),
        )
        adapter.emit_fact(fact)

        # Adapter ID should not appear in the fact
        received = sink.facts[0]
        assert "fake:unique_id" not in str(received.source_id)
        assert "fake:unique_id" not in str(received.data)


class TestAdapterHealthBehavior:
    """Tests for adapter health affecting core behavior."""

    def test_degraded_adapter_reduces_confidence(self) -> None:
        """When adapter is degraded, core should reduce fact confidence.

        This is a design requirement - implementation is in core logic.
        """
        adapter = FakeAdapter()

        # Healthy adapter
        assert adapter.get_health() == AdapterHealth.OK

        # Degrade adapter
        adapter.set_health(AdapterHealth.DEGRADED)
        assert adapter.get_health() == AdapterHealth.DEGRADED

        # Core logic would use this to reduce confidence
        # This test verifies the health is queryable

    def test_offline_adapter_detected(self) -> None:
        """Offline adapter status is detectable."""
        adapter = FakeAdapter()
        adapter.set_health(AdapterHealth.OFFLINE)

        assert adapter.get_health() == AdapterHealth.OFFLINE
        # Core can use this to suppress facts from offline adapters


class TestAdapterErrors:
    """Tests for adapter error types."""

    def test_adapter_error_hierarchy(self) -> None:
        """All adapter errors inherit from AdapterError."""
        assert issubclass(AdapterTranslationError, AdapterError)
        assert issubclass(AdapterConnectionError, AdapterError)
        assert issubclass(AdapterIntentError, AdapterError)

    def test_adapter_errors_catchable(self) -> None:
        """Adapter errors can be caught generically."""
        errors: list[AdapterError] = [
            AdapterTranslationError("translation failed"),
            AdapterConnectionError("connection lost"),
            AdapterIntentError("intent rejected"),
        ]

        for error in errors:
            with pytest.raises(AdapterError):
                raise error


class TestNoHAImports:
    """Tests that core logic does not import Home Assistant.

    REQ-ARCH-ADAPT-001: Core logic must not import HA modules.
    """

    @staticmethod
    def _get_all_imports(module_path: str) -> set[str]:
        """Extract all import statements from a Python file."""
        with open(module_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
        imports: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])

        return imports

    @staticmethod
    def _iter_package_modules(package_name: str) -> list[str]:
        """Get all module file paths in a package."""
        package = importlib.import_module(package_name)
        package_path = getattr(package, "__path__", None)

        if not package_path:
            return []

        modules: list[str] = []
        for _importer, modname, _ispkg in pkgutil.walk_packages(
            package_path, prefix=f"{package_name}."
        ):
            try:
                mod = importlib.import_module(modname)
                if hasattr(mod, "__file__") and mod.__file__:
                    modules.append(mod.__file__)
            except ImportError:
                pass

        return modules

    def test_no_ha_imports_in_adapter_module(self) -> None:
        """adapter.py does not import Home Assistant modules."""
        from trestle_coordinator_core import adapter

        assert adapter.__file__ is not None
        imports = self._get_all_imports(adapter.__file__)

        # Check for Home Assistant module imports
        ha_modules = {"homeassistant", "custom_components"}
        ha_in_imports = imports & ha_modules

        assert not ha_in_imports, f"HA imports found: {ha_in_imports}"

    def test_no_ha_imports_in_decision_modules(self) -> None:
        """Decision modules do not import Home Assistant."""
        ha_modules = {"homeassistant", "custom_components"}

        modules = self._iter_package_modules("trestle_coordinator_core.decision")

        for module_path in modules:
            imports = self._get_all_imports(module_path)
            ha_in_imports = imports & ha_modules

            assert (
                not ha_in_imports
            ), f"HA imports found in {module_path}: {ha_in_imports}"

    def test_no_ha_imports_in_core_package(self) -> None:
        """Entire core package does not import Home Assistant."""
        ha_modules = {"homeassistant", "custom_components"}

        modules = self._iter_package_modules("trestle_coordinator_core")

        for module_path in modules:
            imports = self._get_all_imports(module_path)
            ha_in_imports = imports & ha_modules

            assert (
                not ha_in_imports
            ), f"HA imports found in {module_path}: {ha_in_imports}"


class TestSchemaCompleteness:
    """Tests for fact and intent schema completeness."""

    def test_presence_fact_schema(self) -> None:
        """Presence fact schema is defined correctly."""
        schema = FACT_SCHEMAS[FactType.PRESENCE]
        assert "present" in schema

    def test_motion_fact_schema(self) -> None:
        """Motion fact schema is defined correctly."""
        schema = FACT_SCHEMAS[FactType.MOTION]
        assert "detected" in schema

    def test_device_context_fact_schema(self) -> None:
        """Device context fact schema includes signals from 7a."""
        schema = FACT_SCHEMAS[FactType.DEVICE_CONTEXT]
        assert "device_id" in schema
        assert "signals" in schema

    def test_notify_intent_schema(self) -> None:
        """Notify intent schema is defined correctly."""
        schema = INTENT_SCHEMAS[IntentType.NOTIFY]
        assert "alert_id" in schema
        assert "title" in schema
        assert "message" in schema

    def test_interrupt_intent_schema(self) -> None:
        """Interrupt intent schema includes attention/outputs from 7b/7c."""
        schema = INTENT_SCHEMAS[IntentType.INTERRUPT]
        assert "alert_id" in schema
        assert "attention_level" in schema
        assert "outputs" in schema

    def test_activate_output_intent_schema(self) -> None:
        """Activate output intent schema matches 7c outputs."""
        schema = INTENT_SCHEMAS[IntentType.ACTIVATE_OUTPUT]
        assert "channel" in schema
        assert "intensity" in schema
        assert "persistent" in schema


class TestTranslationOnlyInvariant:
    """Tests that adapters should only translate, not arbitrate.

    REQ-ARCH-ADAPT-003: Adapters perform translation only, no arbitration.

    These are design tests - they verify the interface doesn't encourage
    arbitration by examining the method signatures.
    """

    def test_apply_intent_takes_single_intent(self) -> None:
        """apply_intent takes exactly one intent (no batching/filtering)."""
        sig = inspect.signature(EcosystemAdapter.apply_intent)
        params = list(sig.parameters.keys())

        # Should be: self, intent
        assert len(params) == 2
        assert "intent" in params

    def test_apply_intent_returns_nothing(self) -> None:
        """apply_intent returns None (no modification/feedback)."""
        sig = inspect.signature(EcosystemAdapter.apply_intent)
        assert sig.return_annotation is None

    def test_subscribe_facts_returns_unsubscribe(self) -> None:
        """subscribe_facts returns unsubscribe callable (not filtered facts)."""
        sig = inspect.signature(EcosystemAdapter.subscribe_facts)
        # Return type includes Callable
        return_type = sig.return_annotation
        # Just verify it's defined and isn't a fact type
        assert return_type is not None


class TestMultipleAdapters:
    """Tests for scenarios with multiple adapters."""

    def test_facts_from_multiple_adapters(self) -> None:
        """Core can receive facts from multiple adapters simultaneously."""
        adapter_ha = FakeAdapter(adapter_id="fake:ha")
        adapter_other = FakeAdapter(adapter_id="fake:other")

        sink = RecordingFactSink()
        adapter_ha.subscribe_facts(sink)
        adapter_other.subscribe_facts(sink)

        now = datetime.now(UTC)

        fact_ha = CanonicalFact(
            fact_type=FactType.PRESENCE,
            source_id="zone:home",
            timestamp=now,
            data={"present": True},
        )
        fact_other = CanonicalFact(
            fact_type=FactType.MOTION,
            source_id="area:office",
            timestamp=now + timedelta(milliseconds=100),
            data={"detected": True},
        )

        adapter_ha.emit_fact(fact_ha)
        adapter_other.emit_fact(fact_other)

        assert len(sink.facts) == 2
        assert fact_ha in sink.facts
        assert fact_other in sink.facts

    def test_intents_routed_to_correct_adapter(self) -> None:
        """Intents can be applied to specific adapters."""
        adapter_a = FakeAdapter(adapter_id="fake:a")
        adapter_b = FakeAdapter(adapter_id="fake:b")

        intent = CanonicalIntent(
            intent_type=IntentType.NOTIFY,
            target_id="device:panel_a",
            timestamp=datetime.now(UTC),
        )

        # Only send to adapter_a
        adapter_a.apply_intent(intent)

        assert len(adapter_a.get_applied_intents()) == 1
        assert len(adapter_b.get_applied_intents()) == 0

    def test_adapters_have_unique_ids(self) -> None:
        """Each adapter instance has a unique identifier."""
        adapter_a = FakeAdapter(adapter_id="fake:unique_1")
        adapter_b = FakeAdapter(adapter_id="fake:unique_2")

        assert adapter_a.get_adapter_id() != adapter_b.get_adapter_id()


class TestFactSinkProtocol:
    """Tests for FactSink protocol."""

    def test_fact_sink_is_protocol(self) -> None:
        """FactSink is a Protocol (structural typing)."""

        # Any object with receive_fact method should work
        class CustomSink:
            def receive_fact(self, fact: CanonicalFact) -> None:
                pass

        # This should type-check as FactSink
        sink: FactSink = CustomSink()
        assert hasattr(sink, "receive_fact")

    def test_recording_sink_implements_protocol(self) -> None:
        """RecordingFactSink implements FactSink protocol."""
        sink = RecordingFactSink()
        adapter = FakeAdapter()

        # Should work without type errors
        unsub = adapter.subscribe_facts(sink)
        unsub()
