"""Tests for Slice 7c - Attention → Realization Mapping.

These tests verify that:
- Attention levels map to correct realization intents
- Device capabilities filter outputs correctly
- Safety invariants are maintained
- Output is deterministic
"""

import pytest

from trestle_coordinator_core.decision.attention import AttentionLevel
from trestle_coordinator_core.decision.realization_intent import (
    REALIZATION_PROFILES,
    OutputChannel,
    RealizationIntent,
    produce_realization_frame,
    realize_attention,
)
from trestle_coordinator_core.decision.selection import DeviceContext

# --------------------------------------------------------------------------
# Test Fixtures
# --------------------------------------------------------------------------


def device_with_all_capabilities() -> DeviceContext:
    """Device that supports all output channels."""
    return DeviceContext(
        device_id="full-device",
        signals={
            "supports_audio": True,
            "supports_haptic": True,
            "supports_ambient": True,
        },
    )


def device_visual_only() -> DeviceContext:
    """Device that only supports visual output."""
    return DeviceContext(
        device_id="visual-only",
        signals={
            "supports_audio": False,
            "supports_haptic": False,
            "supports_ambient": False,
        },
    )


def device_with_audio() -> DeviceContext:
    """Device that supports visual and audio."""
    return DeviceContext(
        device_id="audio-device",
        signals={
            "supports_audio": True,
            "supports_haptic": False,
            "supports_ambient": False,
        },
    )


def device_ambient_only() -> DeviceContext:
    """Device that only supports ambient (e.g., smart bulb)."""
    return DeviceContext(
        device_id="ambient-device",
        signals={
            "supports_audio": False,
            "supports_haptic": False,
            "supports_ambient": True,
        },
    )


# --------------------------------------------------------------------------
# Test: RealizationIntent Dataclass
# --------------------------------------------------------------------------


class TestRealizationIntent:
    """Tests for RealizationIntent dataclass."""

    def test_frozen_immutable(self) -> None:
        """Intent is immutable."""
        intent = RealizationIntent(
            channel=OutputChannel.VISUAL,
            intensity="high",
            persistent=True,
            interruptive=True,
        )
        with pytest.raises(AttributeError):
            intent.intensity = "low"  # type: ignore[misc]

    def test_to_dict_format(self) -> None:
        """to_dict produces ICD-compatible format."""
        intent = RealizationIntent(
            channel=OutputChannel.AUDIO,
            intensity="medium",
            persistent=True,
            interruptive=False,
        )
        d = intent.to_dict()
        assert d == {
            "channel": "audio",
            "intensity": "medium",
            "persistent": True,
            "interruptive": False,
        }

    def test_default_values(self) -> None:
        """Default values for persistent and interruptive are False."""
        intent = RealizationIntent(
            channel=OutputChannel.VISUAL,
            intensity="low",
        )
        assert intent.persistent is False
        assert intent.interruptive is False


# --------------------------------------------------------------------------
# Test: OutputChannel Enum
# --------------------------------------------------------------------------


class TestOutputChannel:
    """Tests for OutputChannel enum."""

    def test_all_channels_exist(self) -> None:
        """All expected channels are defined."""
        assert OutputChannel.VISUAL.value == "visual"
        assert OutputChannel.AUDIO.value == "audio"
        assert OutputChannel.HAPTIC.value == "haptic"
        assert OutputChannel.AMBIENT.value == "ambient"

    def test_channel_count(self) -> None:
        """Exactly 4 channels defined."""
        assert len(OutputChannel) == 4


# --------------------------------------------------------------------------
# Test: REALIZATION_PROFILES Static Mapping
# --------------------------------------------------------------------------


class TestRealizationProfiles:
    """Tests for the static realization profiles."""

    def test_all_attention_levels_have_profiles(self) -> None:
        """Every attention level has a realization profile."""
        for level in AttentionLevel:
            assert level in REALIZATION_PROFILES

    def test_passive_is_ambient_only(self) -> None:
        """PASSIVE only produces ambient output."""
        intents = REALIZATION_PROFILES[AttentionLevel.PASSIVE]
        assert len(intents) == 1
        assert intents[0].channel == OutputChannel.AMBIENT
        assert intents[0].intensity == "low"
        assert intents[0].persistent is False
        assert intents[0].interruptive is False

    def test_glance_is_visual_only(self) -> None:
        """GLANCE only produces visual output."""
        intents = REALIZATION_PROFILES[AttentionLevel.GLANCE]
        assert len(intents) == 1
        assert intents[0].channel == OutputChannel.VISUAL
        assert intents[0].intensity == "low"
        assert intents[0].interruptive is False

    def test_notify_has_visual_and_audio(self) -> None:
        """NOTIFY produces visual (persistent) and audio (optional)."""
        intents = REALIZATION_PROFILES[AttentionLevel.NOTIFY]
        channels = {i.channel for i in intents}
        assert OutputChannel.VISUAL in channels
        assert OutputChannel.AUDIO in channels
        # Visual should be persistent
        visual = next(i for i in intents if i.channel == OutputChannel.VISUAL)
        assert visual.persistent is True
        assert visual.intensity == "medium"

    def test_interrupt_has_three_channels(self) -> None:
        """INTERRUPT produces visual, audio, and haptic."""
        intents = REALIZATION_PROFILES[AttentionLevel.INTERRUPT]
        channels = {i.channel for i in intents}
        assert OutputChannel.VISUAL in channels
        assert OutputChannel.AUDIO in channels
        assert OutputChannel.HAPTIC in channels
        # All should be interruptive
        for intent in intents:
            assert intent.interruptive is True

    def test_critical_has_three_channels_all_persistent(self) -> None:
        """CRITICAL produces visual, audio, haptic - all persistent."""
        intents = REALIZATION_PROFILES[AttentionLevel.CRITICAL]
        channels = {i.channel for i in intents}
        assert OutputChannel.VISUAL in channels
        assert OutputChannel.AUDIO in channels
        assert OutputChannel.HAPTIC in channels
        # All should be persistent and high intensity
        for intent in intents:
            assert intent.persistent is True
            assert intent.intensity == "high"
            assert intent.interruptive is True


# --------------------------------------------------------------------------
# Test: realize_attention() Function
# --------------------------------------------------------------------------


class TestRealizeAttention:
    """Tests for the realize_attention function."""

    def test_full_device_gets_all_intents(self) -> None:
        """Device with all capabilities gets all intents."""
        device = device_with_all_capabilities()
        intents = realize_attention(AttentionLevel.CRITICAL, device)
        # CRITICAL has visual, audio, haptic
        channels = {i.channel for i in intents}
        assert len(channels) == 3

    def test_visual_only_device_gets_visual_only(self) -> None:
        """Device without audio/haptic only gets visual."""
        device = device_visual_only()
        intents = realize_attention(AttentionLevel.INTERRUPT, device)
        assert len(intents) == 1
        assert intents[0].channel == OutputChannel.VISUAL

    def test_audio_device_gets_visual_and_audio(self) -> None:
        """Device with audio gets visual and audio but not haptic."""
        device = device_with_audio()
        intents = realize_attention(AttentionLevel.INTERRUPT, device)
        channels = {i.channel for i in intents}
        assert OutputChannel.VISUAL in channels
        assert OutputChannel.AUDIO in channels
        assert OutputChannel.HAPTIC not in channels

    def test_passive_on_non_ambient_device_empty(self) -> None:
        """PASSIVE on device without ambient support returns empty."""
        device = device_visual_only()
        intents = realize_attention(AttentionLevel.PASSIVE, device)
        # PASSIVE only has AMBIENT, which isn't supported
        assert intents == []

    def test_passive_on_ambient_device(self) -> None:
        """PASSIVE on device with ambient support returns ambient."""
        device = device_ambient_only()
        intents = realize_attention(AttentionLevel.PASSIVE, device)
        assert len(intents) == 1
        assert intents[0].channel == OutputChannel.AMBIENT


# --------------------------------------------------------------------------
# Test: Device Capability Filtering
# --------------------------------------------------------------------------


class TestCapabilityFiltering:
    """Tests for device capability filtering behavior."""

    def test_audio_filtered_when_not_supported(self) -> None:
        """Audio intents are dropped when device doesn't support audio."""
        device = DeviceContext(
            device_id="no-audio",
            signals={"supports_audio": False},
        )
        intents = realize_attention(AttentionLevel.NOTIFY, device)
        channels = [i.channel for i in intents]
        assert OutputChannel.AUDIO not in channels
        assert OutputChannel.VISUAL in channels

    def test_haptic_filtered_when_not_supported(self) -> None:
        """Haptic intents are dropped when device doesn't support haptic."""
        device = DeviceContext(
            device_id="no-haptic",
            signals={"supports_audio": True, "supports_haptic": False},
        )
        intents = realize_attention(AttentionLevel.INTERRUPT, device)
        channels = [i.channel for i in intents]
        assert OutputChannel.HAPTIC not in channels

    def test_visual_always_passes(self) -> None:
        """Visual is always supported regardless of signals."""
        device = DeviceContext(
            device_id="basic",
            signals={},  # No explicit capabilities
        )
        intents = realize_attention(AttentionLevel.GLANCE, device)
        assert len(intents) == 1
        assert intents[0].channel == OutputChannel.VISUAL

    def test_filtering_never_downgrades_attention(self) -> None:
        """Filtering removes channels but never changes intent properties."""
        device = device_visual_only()
        intents = realize_attention(AttentionLevel.CRITICAL, device)
        # Should still have CRITICAL properties on remaining intent
        assert len(intents) == 1
        assert intents[0].intensity == "high"
        assert intents[0].persistent is True
        assert intents[0].interruptive is True

    def test_default_audio_supported(self) -> None:
        """Audio is supported by default if not explicitly disabled."""
        device = DeviceContext(device_id="default", signals={})
        intents = realize_attention(AttentionLevel.NOTIFY, device)
        channels = [i.channel for i in intents]
        # Audio defaults to True
        assert OutputChannel.AUDIO in channels


# --------------------------------------------------------------------------
# Test: Safety Invariants
# --------------------------------------------------------------------------


class TestSafetyInvariants:
    """Tests for safety invariants that must always hold."""

    def test_critical_always_produces_at_least_two_outputs_on_full_device(
        self,
    ) -> None:
        """CRITICAL produces multiple outputs on capable device."""
        device = device_with_all_capabilities()
        intents = realize_attention(AttentionLevel.CRITICAL, device)
        assert len(intents) >= 2

    def test_passive_never_interruptive(self) -> None:
        """PASSIVE intents are never interruptive."""
        intents = REALIZATION_PROFILES[AttentionLevel.PASSIVE]
        for intent in intents:
            assert intent.interruptive is False

    def test_passive_never_persistent(self) -> None:
        """PASSIVE intents are never persistent."""
        intents = REALIZATION_PROFILES[AttentionLevel.PASSIVE]
        for intent in intents:
            assert intent.persistent is False

    def test_glance_never_audio(self) -> None:
        """GLANCE never produces audio output."""
        intents = REALIZATION_PROFILES[AttentionLevel.GLANCE]
        channels = [i.channel for i in intents]
        assert OutputChannel.AUDIO not in channels

    def test_critical_always_persistent(self) -> None:
        """CRITICAL intents are always persistent."""
        intents = REALIZATION_PROFILES[AttentionLevel.CRITICAL]
        for intent in intents:
            assert intent.persistent is True

    def test_no_interruptive_below_interrupt_level(self) -> None:
        """No output is interruptive unless level >= INTERRUPT."""
        non_interruptive_levels = [
            AttentionLevel.PASSIVE,
            AttentionLevel.GLANCE,
            AttentionLevel.NOTIFY,
        ]
        for level in non_interruptive_levels:
            intents = REALIZATION_PROFILES[level]
            for intent in intents:
                assert (
                    intent.interruptive is False
                ), f"{level} should not have interruptive intents"

    def test_interrupt_and_above_are_interruptive(self) -> None:
        """INTERRUPT and CRITICAL levels have interruptive outputs."""
        for level in [AttentionLevel.INTERRUPT, AttentionLevel.CRITICAL]:
            intents = REALIZATION_PROFILES[level]
            # At least one should be interruptive
            assert any(i.interruptive for i in intents)


# --------------------------------------------------------------------------
# Test: Determinism
# --------------------------------------------------------------------------


class TestDeterminism:
    """Tests for deterministic output."""

    def test_same_input_same_output(self) -> None:
        """Identical inputs produce identical outputs."""
        device = device_with_all_capabilities()
        intents1 = realize_attention(AttentionLevel.INTERRUPT, device)
        intents2 = realize_attention(AttentionLevel.INTERRUPT, device)
        assert intents1 == intents2

    def test_order_preserved(self) -> None:
        """Output order is consistent across calls."""
        device = device_with_all_capabilities()
        for _ in range(10):
            intents = realize_attention(AttentionLevel.CRITICAL, device)
            channels = [i.channel for i in intents]
            # Order should be consistent
            assert channels == [
                OutputChannel.VISUAL,
                OutputChannel.AUDIO,
                OutputChannel.HAPTIC,
            ]


# --------------------------------------------------------------------------
# Test: ICD Frame Production
# --------------------------------------------------------------------------


class TestProduceRealizationFrame:
    """Tests for produce_realization_frame function."""

    def test_frame_structure(self) -> None:
        """Frame has required ICD structure."""
        intents = [
            RealizationIntent(
                channel=OutputChannel.VISUAL,
                intensity="high",
                persistent=True,
                interruptive=True,
            )
        ]
        frame = produce_realization_frame(
            alert_id="test-123",
            attention=AttentionLevel.CRITICAL,
            intents=intents,
        )
        assert frame["type"] == "alert_realization"
        assert frame["alert_id"] == "test-123"
        assert frame["attention"] == "CRITICAL"
        assert len(frame["outputs"]) == 1

    def test_frame_outputs_match_intents(self) -> None:
        """Frame outputs match input intents."""
        device = device_with_all_capabilities()
        intents = realize_attention(AttentionLevel.INTERRUPT, device)
        frame = produce_realization_frame(
            alert_id="alert-456",
            attention=AttentionLevel.INTERRUPT,
            intents=intents,
        )
        assert len(frame["outputs"]) == len(intents)
        for output, intent in zip(frame["outputs"], intents, strict=True):
            assert output["channel"] == intent.channel.value
            assert output["intensity"] == intent.intensity

    def test_empty_intents_produces_empty_outputs(self) -> None:
        """Empty intent list produces empty outputs array."""
        frame = produce_realization_frame(
            alert_id="empty-alert",
            attention=AttentionLevel.PASSIVE,
            intents=[],
        )
        assert frame["outputs"] == []

    def test_frame_is_serializable(self) -> None:
        """Frame is JSON-serializable (no complex objects)."""
        import json

        device = device_with_all_capabilities()
        intents = realize_attention(AttentionLevel.CRITICAL, device)
        frame = produce_realization_frame(
            alert_id="serialize-test",
            attention=AttentionLevel.CRITICAL,
            intents=intents,
        )
        # Should not raise
        json_str = json.dumps(frame)
        assert isinstance(json_str, str)


# --------------------------------------------------------------------------
# Test: Edge Cases
# --------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and unusual scenarios."""

    def test_unknown_signal_keys_ignored(self) -> None:
        """Unknown signal keys don't affect behavior."""
        device = DeviceContext(
            device_id="unknown-signals",
            signals={
                "supports_audio": True,
                "unknown_capability": True,
                "future_feature": "value",
            },
        )
        # Should work normally
        intents = realize_attention(AttentionLevel.NOTIFY, device)
        assert len(intents) == 2

    def test_empty_signals_uses_defaults(self) -> None:
        """Empty signals dict uses safe defaults."""
        device = DeviceContext(device_id="empty", signals={})
        intents = realize_attention(AttentionLevel.NOTIFY, device)
        # Audio defaults to True, so both visual and audio should appear
        channels = [i.channel for i in intents]
        assert OutputChannel.VISUAL in channels
        assert OutputChannel.AUDIO in channels

    def test_all_channels_filtered_returns_empty(self) -> None:
        """If all channels are filtered, return empty list."""
        # Create device that only supports audio (not visual)
        # This is unrealistic but tests the filtering logic
        device = DeviceContext(
            device_id="weird",
            signals={
                "supports_audio": False,
                "supports_haptic": False,
                "supports_ambient": False,
            },
        )
        # PASSIVE only has AMBIENT
        intents = realize_attention(AttentionLevel.PASSIVE, device)
        assert intents == []
