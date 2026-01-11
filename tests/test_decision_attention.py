"""Tests for attention and interruption model (Slice 7b).

Tests verify:
- Quiet hours suppression
- Life-safety bypass
- Presence-based elevation
- Escalation increases attention
- Cooldown suppression
- Determinism (identical input → identical output)
- Safety invariants
"""

from __future__ import annotations

from trestle_coordinator_core.decision.attention import (
    INTERRUPT_THRESHOLD,
    LIFE_SAFETY_THRESHOLD,
    PRIORITY_CRITICAL,
    PRIORITY_GLANCE,
    PRIORITY_INTERRUPT,
    PRIORITY_NOTIFY,
    AttentionContext,
    AttentionLevel,
    compute_attention_level,
    compute_attention_level_from_device,
)
from trestle_coordinator_core.decision.selection import DeviceContext


class TestAttentionLevelComparison:
    """Test AttentionLevel enum comparison operators."""

    def test_ordering_passive_is_lowest(self) -> None:
        """PASSIVE is the lowest attention level."""
        assert AttentionLevel.PASSIVE < AttentionLevel.GLANCE
        assert AttentionLevel.PASSIVE < AttentionLevel.NOTIFY
        assert AttentionLevel.PASSIVE < AttentionLevel.INTERRUPT
        assert AttentionLevel.PASSIVE < AttentionLevel.CRITICAL

    def test_ordering_critical_is_highest(self) -> None:
        """CRITICAL is the highest attention level."""
        assert AttentionLevel.CRITICAL > AttentionLevel.PASSIVE
        assert AttentionLevel.CRITICAL > AttentionLevel.GLANCE
        assert AttentionLevel.CRITICAL > AttentionLevel.NOTIFY
        assert AttentionLevel.CRITICAL > AttentionLevel.INTERRUPT

    def test_ordering_full_sequence(self) -> None:
        """Full ordering: PASSIVE < GLANCE < NOTIFY < INTERRUPT < CRITICAL."""
        levels = [
            AttentionLevel.PASSIVE,
            AttentionLevel.GLANCE,
            AttentionLevel.NOTIFY,
            AttentionLevel.INTERRUPT,
            AttentionLevel.CRITICAL,
        ]
        for i in range(len(levels) - 1):
            assert levels[i] < levels[i + 1]

    def test_equality(self) -> None:
        """Same level equals itself."""
        assert AttentionLevel.NOTIFY == AttentionLevel.NOTIFY
        assert not (AttentionLevel.NOTIFY < AttentionLevel.NOTIFY)
        assert AttentionLevel.NOTIFY <= AttentionLevel.NOTIFY
        assert AttentionLevel.NOTIFY >= AttentionLevel.NOTIFY


class TestCriticalBypass:
    """Test Rule 1: Critical bypass for life-safety alerts."""

    def test_life_safety_threshold_returns_critical(self) -> None:
        """Priority at LIFE_SAFETY_THRESHOLD returns CRITICAL."""
        context = AttentionContext(alert_priority=LIFE_SAFETY_THRESHOLD)
        assert compute_attention_level(context) == AttentionLevel.CRITICAL

    def test_above_life_safety_returns_critical(self) -> None:
        """Priority above LIFE_SAFETY_THRESHOLD returns CRITICAL."""
        context = AttentionContext(alert_priority=LIFE_SAFETY_THRESHOLD + 30)
        assert compute_attention_level(context) == AttentionLevel.CRITICAL

    def test_critical_bypasses_quiet_hours(self) -> None:
        """CRITICAL level bypasses quiet hours."""
        context = AttentionContext(
            alert_priority=LIFE_SAFETY_THRESHOLD,
            quiet_hours=True,
        )
        assert compute_attention_level(context) == AttentionLevel.CRITICAL

    def test_critical_bypasses_cooldown(self) -> None:
        """CRITICAL level bypasses cooldown suppression."""
        context = AttentionContext(
            alert_priority=LIFE_SAFETY_THRESHOLD,
            cooldown_active=True,
            escalation_level=0,
        )
        assert compute_attention_level(context) == AttentionLevel.CRITICAL

    def test_critical_bypasses_ambient_only_device(self) -> None:
        """CRITICAL level bypasses ambient-only device cap."""
        context = AttentionContext(
            alert_priority=LIFE_SAFETY_THRESHOLD,
            device_supports_interruptions=False,
        )
        assert compute_attention_level(context) == AttentionLevel.CRITICAL


class TestCooldownSuppression:
    """Test Rule 2: Cooldown suppression."""

    def test_cooldown_with_no_escalation_returns_passive(self) -> None:
        """Cooldown active with no escalation returns PASSIVE."""
        context = AttentionContext(
            alert_priority=80,
            cooldown_active=True,
            escalation_level=0,
        )
        assert compute_attention_level(context) == AttentionLevel.PASSIVE

    def test_cooldown_with_escalation_not_suppressed(self) -> None:
        """Cooldown with escalation is not suppressed."""
        context = AttentionContext(
            alert_priority=80,
            cooldown_active=True,
            escalation_level=1,
        )
        result = compute_attention_level(context)
        assert result != AttentionLevel.PASSIVE

    def test_no_cooldown_not_suppressed(self) -> None:
        """No cooldown means no suppression."""
        context = AttentionContext(
            alert_priority=80,
            cooldown_active=False,
            escalation_level=0,
        )
        result = compute_attention_level(context)
        assert result != AttentionLevel.PASSIVE


class TestBasePriorityMapping:
    """Test Rule 3: Base attention level from priority."""

    def test_priority_1_returns_passive(self) -> None:
        """Very low priority returns PASSIVE."""
        context = AttentionContext(alert_priority=1)
        assert compute_attention_level(context) == AttentionLevel.PASSIVE

    def test_priority_19_returns_passive(self) -> None:
        """Priority 19 (below GLANCE threshold) returns PASSIVE."""
        context = AttentionContext(alert_priority=19)
        assert compute_attention_level(context) == AttentionLevel.PASSIVE

    def test_priority_20_returns_glance(self) -> None:
        """Priority at GLANCE threshold returns GLANCE."""
        context = AttentionContext(alert_priority=PRIORITY_GLANCE)
        assert compute_attention_level(context) == AttentionLevel.GLANCE

    def test_priority_49_returns_glance(self) -> None:
        """Priority 49 (below NOTIFY threshold) returns GLANCE."""
        context = AttentionContext(alert_priority=49)
        assert compute_attention_level(context) == AttentionLevel.GLANCE

    def test_priority_50_returns_notify(self) -> None:
        """Priority at NOTIFY threshold returns NOTIFY."""
        context = AttentionContext(alert_priority=PRIORITY_NOTIFY)
        assert compute_attention_level(context) == AttentionLevel.NOTIFY

    def test_priority_80_returns_notify(self) -> None:
        """Priority 80 (typical alert) returns NOTIFY."""
        context = AttentionContext(alert_priority=80)
        assert compute_attention_level(context) == AttentionLevel.NOTIFY

    def test_priority_100_returns_interrupt(self) -> None:
        """Priority at INTERRUPT threshold returns INTERRUPT."""
        context = AttentionContext(alert_priority=PRIORITY_INTERRUPT)
        assert compute_attention_level(context) == AttentionLevel.INTERRUPT

    def test_priority_120_returns_interrupt(self) -> None:
        """Priority 120 returns INTERRUPT."""
        context = AttentionContext(alert_priority=120)
        assert compute_attention_level(context) == AttentionLevel.INTERRUPT


class TestEscalation:
    """Test Rule 6: Escalation increases attention."""

    def test_escalation_level_1_increases_one_step(self) -> None:
        """Escalation level 1 increases attention by one step."""
        # NOTIFY (priority 80) + escalation 1 → INTERRUPT
        context = AttentionContext(
            alert_priority=80,
            escalation_level=1,
        )
        assert compute_attention_level(context) == AttentionLevel.INTERRUPT

    def test_escalation_level_2_increases_two_steps(self) -> None:
        """Escalation level 2 increases attention by two steps."""
        # GLANCE (priority 30) + escalation 2 → INTERRUPT
        context = AttentionContext(
            alert_priority=30,
            escalation_level=2,
        )
        assert compute_attention_level(context) == AttentionLevel.INTERRUPT

    def test_escalation_capped_at_critical(self) -> None:
        """Escalation cannot exceed CRITICAL."""
        # NOTIFY + escalation 5 → still CRITICAL (not beyond)
        context = AttentionContext(
            alert_priority=80,
            escalation_level=5,
        )
        assert compute_attention_level(context) == AttentionLevel.CRITICAL

    def test_escalation_zero_no_change(self) -> None:
        """Escalation level 0 does not change attention."""
        context = AttentionContext(
            alert_priority=80,
            escalation_level=0,
        )
        assert compute_attention_level(context) == AttentionLevel.NOTIFY


class TestPresenceModulation:
    """Test Rule 4 & 5: Device presence modulation."""

    def test_nearby_and_recently_active_increases_attention(self) -> None:
        """User nearby AND recently active increases attention."""
        # NOTIFY → INTERRUPT when nearby and active
        context = AttentionContext(
            alert_priority=80,
            device_proximity_near=True,
            device_recently_active=True,
        )
        assert compute_attention_level(context) == AttentionLevel.INTERRUPT

    def test_nearby_only_no_increase(self) -> None:
        """Nearby alone (without recent activity) does not increase."""
        context = AttentionContext(
            alert_priority=80,
            device_proximity_near=True,
            device_recently_active=False,
        )
        assert compute_attention_level(context) == AttentionLevel.NOTIFY

    def test_recently_active_only_no_increase(self) -> None:
        """Recently active alone (without proximity) does not increase."""
        context = AttentionContext(
            alert_priority=80,
            device_proximity_near=False,
            device_recently_active=True,
        )
        assert compute_attention_level(context) == AttentionLevel.NOTIFY

    def test_no_presence_baseline(self) -> None:
        """No presence signals uses baseline attention."""
        context = AttentionContext(
            alert_priority=80,
            device_proximity_near=False,
            device_recently_active=False,
        )
        assert compute_attention_level(context) == AttentionLevel.NOTIFY


class TestAmbientOnlyDevices:
    """Test Rule 5: Ambient-only device capping."""

    def test_ambient_only_caps_at_glance(self) -> None:
        """Device without interruption support caps at GLANCE."""
        context = AttentionContext(
            alert_priority=80,  # Would normally be NOTIFY
            device_supports_interruptions=False,
        )
        assert compute_attention_level(context) == AttentionLevel.GLANCE

    def test_ambient_only_caps_interrupt(self) -> None:
        """INTERRUPT capped to GLANCE on ambient-only device."""
        context = AttentionContext(
            alert_priority=120,  # Would normally be INTERRUPT
            device_supports_interruptions=False,
        )
        assert compute_attention_level(context) == AttentionLevel.GLANCE

    def test_passive_not_elevated_by_ambient_cap(self) -> None:
        """PASSIVE stays PASSIVE on ambient-only device."""
        context = AttentionContext(
            alert_priority=10,
            device_supports_interruptions=False,
        )
        assert compute_attention_level(context) == AttentionLevel.PASSIVE

    def test_critical_bypasses_ambient_cap(self) -> None:
        """CRITICAL bypasses ambient-only cap (life safety)."""
        context = AttentionContext(
            alert_priority=LIFE_SAFETY_THRESHOLD,
            device_supports_interruptions=False,
        )
        assert compute_attention_level(context) == AttentionLevel.CRITICAL


class TestQuietHoursGating:
    """Test Rule 7: Quiet hours gating."""

    def test_quiet_hours_caps_interrupt_at_notify(self) -> None:
        """INTERRUPT capped to NOTIFY during quiet hours."""
        context = AttentionContext(
            alert_priority=120,  # Would be INTERRUPT
            quiet_hours=True,
        )
        assert compute_attention_level(context) == AttentionLevel.NOTIFY

    def test_quiet_hours_allows_notify(self) -> None:
        """NOTIFY allowed during quiet hours."""
        context = AttentionContext(
            alert_priority=80,
            quiet_hours=True,
        )
        assert compute_attention_level(context) == AttentionLevel.NOTIFY

    def test_quiet_hours_allows_glance(self) -> None:
        """GLANCE allowed during quiet hours."""
        context = AttentionContext(
            alert_priority=30,
            quiet_hours=True,
        )
        assert compute_attention_level(context) == AttentionLevel.GLANCE

    def test_quiet_hours_allows_passive(self) -> None:
        """PASSIVE allowed during quiet hours."""
        context = AttentionContext(
            alert_priority=10,
            quiet_hours=True,
        )
        assert compute_attention_level(context) == AttentionLevel.PASSIVE

    def test_quiet_hours_critical_bypass(self) -> None:
        """CRITICAL bypasses quiet hours (life safety)."""
        context = AttentionContext(
            alert_priority=LIFE_SAFETY_THRESHOLD,
            quiet_hours=True,
        )
        assert compute_attention_level(context) == AttentionLevel.CRITICAL

    def test_quiet_hours_with_escalation_capped(self) -> None:
        """Escalation during quiet hours still capped at NOTIFY."""
        # NOTIFY + escalation 2 → CRITICAL, but capped at NOTIFY
        context = AttentionContext(
            alert_priority=80,
            quiet_hours=True,
            escalation_level=2,
        )
        assert compute_attention_level(context) == AttentionLevel.NOTIFY


class TestDeterminism:
    """Test that computation is deterministic."""

    def test_identical_inputs_identical_outputs(self) -> None:
        """Same inputs always produce same output."""
        context = AttentionContext(
            alert_priority=80,
            alert_domain="motion_detection",
            quiet_hours=False,
            cooldown_active=False,
            escalation_level=1,
            device_present=True,
            device_proximity_near=True,
            device_supports_interruptions=True,
            device_recently_active=True,
        )

        # Call multiple times
        results = [compute_attention_level(context) for _ in range(100)]

        # All results should be identical
        assert all(r == results[0] for r in results)

    def test_frozen_dataclass_hashable(self) -> None:
        """AttentionContext is frozen and can be used in sets."""
        context1 = AttentionContext(alert_priority=80)
        context2 = AttentionContext(alert_priority=80)

        # Same values should be equal
        assert context1 == context2

        # Can be used in sets
        contexts = {context1, context2}
        assert len(contexts) == 1


class TestSafetyInvariants:
    """Test safety invariants that must never be violated."""

    def test_never_exceed_critical(self) -> None:
        """No combination of inputs can exceed CRITICAL."""
        # Maximum everything
        context = AttentionContext(
            alert_priority=199,
            escalation_level=10,
            device_proximity_near=True,
            device_recently_active=True,
        )
        assert compute_attention_level(context) == AttentionLevel.CRITICAL

    def test_never_interrupt_during_quiet_hours_unless_critical(self) -> None:
        """Never INTERRUPT during quiet hours unless CRITICAL."""
        # High priority but below life safety
        context = AttentionContext(
            alert_priority=LIFE_SAFETY_THRESHOLD - 1,
            quiet_hours=True,
            escalation_level=5,
            device_proximity_near=True,
            device_recently_active=True,
        )
        result = compute_attention_level(context)
        assert result <= AttentionLevel.NOTIFY

    def test_life_safety_always_critical(self) -> None:
        """Life safety priority ALWAYS results in CRITICAL."""
        # Even with everything suppressive
        context = AttentionContext(
            alert_priority=LIFE_SAFETY_THRESHOLD,
            quiet_hours=True,
            cooldown_active=True,
            escalation_level=0,
            device_supports_interruptions=False,
        )
        assert compute_attention_level(context) == AttentionLevel.CRITICAL


class TestDeviceContextBridge:
    """Test compute_attention_level_from_device helper."""

    def test_extracts_proximity_signal(self) -> None:
        """Extracts proximity_active from DeviceContext signals."""
        device = DeviceContext(
            device_id="panel-1",
            signals={"proximity_active": True, "recently_active": True},
        )
        result = compute_attention_level_from_device(
            alert_priority=80,
            device=device,
        )
        # Proximity + recently_active should elevate NOTIFY → INTERRUPT
        assert result == AttentionLevel.INTERRUPT

    def test_extracts_supports_interruptions_signal(self) -> None:
        """Extracts supports_interruptions from DeviceContext signals."""
        device = DeviceContext(
            device_id="ambient-1",
            signals={"supports_interruptions": False},
        )
        result = compute_attention_level_from_device(
            alert_priority=80,
            device=device,
        )
        # Should cap at GLANCE
        assert result == AttentionLevel.GLANCE

    def test_missing_signals_use_safe_defaults(self) -> None:
        """Missing signals use conservative defaults."""
        device = DeviceContext(
            device_id="panel-1",
            signals={},  # No signals
        )
        result = compute_attention_level_from_device(
            alert_priority=80,
            device=device,
        )
        # Should use baseline (NOTIFY for priority 80)
        assert result == AttentionLevel.NOTIFY

    def test_passes_quiet_hours(self) -> None:
        """Passes quiet_hours parameter correctly."""
        device = DeviceContext(device_id="panel-1", signals={})
        result = compute_attention_level_from_device(
            alert_priority=120,
            device=device,
            quiet_hours=True,
        )
        # Should cap at NOTIFY
        assert result == AttentionLevel.NOTIFY

    def test_passes_cooldown_and_escalation(self) -> None:
        """Passes cooldown and escalation parameters correctly."""
        device = DeviceContext(device_id="panel-1", signals={})

        # Cooldown with no escalation → PASSIVE
        result = compute_attention_level_from_device(
            alert_priority=80,
            device=device,
            cooldown_active=True,
            escalation_level=0,
        )
        assert result == AttentionLevel.PASSIVE


class TestOutputMappingExamples:
    """Test the example output mappings from the spec."""

    def test_priority_180_critical(self) -> None:
        """Priority 180 → CRITICAL."""
        context = AttentionContext(alert_priority=180)
        assert compute_attention_level(context) == AttentionLevel.CRITICAL

    def test_priority_120_quiet_hours_notify(self) -> None:
        """Priority 120, quiet hours → NOTIFY."""
        context = AttentionContext(
            alert_priority=120,
            quiet_hours=True,
        )
        assert compute_attention_level(context) == AttentionLevel.NOTIFY

    def test_priority_80_user_nearby_interrupt(self) -> None:
        """Priority 80, user nearby and active → INTERRUPT."""
        context = AttentionContext(
            alert_priority=80,
            device_proximity_near=True,
            device_recently_active=True,
        )
        assert compute_attention_level(context) == AttentionLevel.INTERRUPT

    def test_priority_80_no_presence_notify(self) -> None:
        """Priority 80, no presence → NOTIFY."""
        context = AttentionContext(
            alert_priority=80,
            device_proximity_near=False,
            device_recently_active=False,
        )
        assert compute_attention_level(context) == AttentionLevel.NOTIFY

    def test_repeated_alert_escalation_interrupt(self) -> None:
        """Repeated alert (escalation=1) → INTERRUPT."""
        # Priority 80 is NOTIFY, + escalation 1 → INTERRUPT
        context = AttentionContext(
            alert_priority=80,
            escalation_level=1,
        )
        assert compute_attention_level(context) == AttentionLevel.INTERRUPT


class TestConstants:
    """Test that constants are correctly defined."""

    def test_life_safety_threshold_value(self) -> None:
        """LIFE_SAFETY_THRESHOLD is 150."""
        assert LIFE_SAFETY_THRESHOLD == 150

    def test_interrupt_threshold_value(self) -> None:
        """INTERRUPT_THRESHOLD is 100."""
        assert INTERRUPT_THRESHOLD == 100

    def test_priority_thresholds_ordering(self) -> None:
        """Priority thresholds are in correct order."""
        assert (
            PRIORITY_GLANCE < PRIORITY_NOTIFY < PRIORITY_INTERRUPT < PRIORITY_CRITICAL
        )
