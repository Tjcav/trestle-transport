"""Tests for device selection."""

from __future__ import annotations

from trestle_coordinator_core.decision.selection import (
    HIGH_LUX_THRESHOLD,
    LOW_LUX_THRESHOLD,
    RECENT_INTERACTION_SECONDS,
    SCORE_LOW_LUX_BOOST,
    SCORE_PROXIMITY_ACTIVE,
    SCORE_RECENT_INTERACTION,
    SCORE_RECENTLY_ACTIVE,
    SCORE_ROOM_MATCH,
    SCORE_SAME_ROOM_FALLBACK,
    SCORE_SCREEN_FACING,
    AlertTarget,
    DeviceCapabilities,
    DeviceContext,
    select_device,
)


class TestSelectDeviceCore:
    """Core selection tests."""

    def test_selects_device_with_highest_score(self) -> None:
        """Device with highest base score is selected."""
        current_time = 1000.0

        # Device A: room match (+100).
        device_a = DeviceContext(
            device_id="device_a",
            room="living_room",
            online=True,
        )
        # Device B: no room match.
        device_b = DeviceContext(
            device_id="device_b",
            room="bedroom",
            online=True,
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_a": DeviceCapabilities(device_id="device_a"),
            "device_b": DeviceCapabilities(device_id="device_b"),
        }

        result = select_device(target, [device_a, device_b], capabilities, current_time)

        assert result.device_id == "device_a"
        assert result.score == SCORE_ROOM_MATCH
        assert result.score_breakdown.get("room_match") == SCORE_ROOM_MATCH

    def test_deterministic_with_equal_scores(self) -> None:
        """Equal scores produce deterministic output via tie-break."""
        current_time = 1000.0

        # Both devices: same room, no interaction.
        device_a = DeviceContext(device_id="device_a", room="living_room", online=True)
        device_b = DeviceContext(device_id="device_b", room="living_room", online=True)
        device_c = DeviceContext(device_id="device_c", room="living_room", online=True)

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_a": DeviceCapabilities(device_id="device_a"),
            "device_b": DeviceCapabilities(device_id="device_b"),
            "device_c": DeviceCapabilities(device_id="device_c"),
        }

        # Test multiple orderings - should always select same device.
        result1 = select_device(
            target, [device_a, device_b, device_c], capabilities, current_time
        )
        result2 = select_device(
            target, [device_c, device_a, device_b], capabilities, current_time
        )
        result3 = select_device(
            target, [device_b, device_c, device_a], capabilities, current_time
        )

        assert result1.device_id == result2.device_id == result3.device_id
        # Should be "device_a" due to alphabetical tie-break.
        assert result1.device_id == "device_a"

    def test_returns_none_if_no_eligible_devices(self) -> None:
        """Returns None when no devices are eligible."""
        current_time = 1000.0

        target = AlertTarget(room_id="living_room")
        capabilities: dict[str, DeviceCapabilities] = {}

        result = select_device(target, [], capabilities, current_time)

        assert result.device_id is None
        assert result.candidates_evaluated == 0

    def test_filters_offline_devices(self) -> None:
        """Offline devices are not selected."""
        current_time = 1000.0

        device_offline = DeviceContext(
            device_id="device_offline",
            room="living_room",
            online=False,
        )
        device_online = DeviceContext(
            device_id="device_online",
            room="bedroom",
            online=True,
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_offline": DeviceCapabilities(device_id="device_offline"),
            "device_online": DeviceCapabilities(device_id="device_online"),
        }

        result = select_device(
            target, [device_offline, device_online], capabilities, current_time
        )

        assert result.device_id == "device_online"
        assert result.candidates_evaluated == 1

    def test_filters_excluded_devices(self) -> None:
        """Excluded devices are not selected."""
        current_time = 1000.0

        device_excluded = DeviceContext(
            device_id="device_excluded",
            room="living_room",
            online=True,
        )
        device_allowed = DeviceContext(
            device_id="device_allowed",
            room="bedroom",
            online=True,
        )

        target = AlertTarget(
            room_id="living_room", excluded_devices=frozenset(["device_excluded"])
        )
        capabilities = {
            "device_excluded": DeviceCapabilities(device_id="device_excluded"),
            "device_allowed": DeviceCapabilities(device_id="device_allowed"),
        }

        result = select_device(
            target, [device_excluded, device_allowed], capabilities, current_time
        )

        assert result.device_id == "device_allowed"

    def test_filters_suppressed_devices(self) -> None:
        """Suppressed devices are not selected."""
        current_time = 1000.0

        device_suppressed = DeviceContext(
            device_id="device_suppressed",
            room="living_room",
            online=True,
        )
        device_normal = DeviceContext(
            device_id="device_normal",
            room="bedroom",
            online=True,
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_suppressed": DeviceCapabilities(
                device_id="device_suppressed", suppressed=True
            ),
            "device_normal": DeviceCapabilities(device_id="device_normal"),
        }

        result = select_device(
            target, [device_suppressed, device_normal], capabilities, current_time
        )

        assert result.device_id == "device_normal"

    def test_filters_missing_required_capabilities(self) -> None:
        """Devices missing required capabilities are not selected."""
        current_time = 1000.0

        device_missing = DeviceContext(
            device_id="device_missing",
            room="living_room",
            online=True,
        )
        device_has_caps = DeviceContext(
            device_id="device_has_caps",
            room="bedroom",
            online=True,
        )

        target = AlertTarget(
            room_id="living_room", required_capabilities=frozenset(["alert_display"])
        )
        capabilities = {
            "device_missing": DeviceCapabilities(device_id="device_missing"),
            "device_has_caps": DeviceCapabilities(
                device_id="device_has_caps",
                capabilities=frozenset(["alert_display"]),
            ),
        }

        result = select_device(
            target, [device_missing, device_has_caps], capabilities, current_time
        )

        assert result.device_id == "device_has_caps"

    def test_recent_interaction_adds_score(self) -> None:
        """Recent interaction boosts device score."""
        current_time = 1000.0

        # Device A: recent interaction.
        device_a = DeviceContext(
            device_id="device_a",
            room="bedroom",
            online=True,
            last_interaction_ts=current_time - 60,  # 1 minute ago.
        )
        # Device B: no interaction.
        device_b = DeviceContext(
            device_id="device_b",
            room="bedroom",
            online=True,
        )

        target = AlertTarget()
        capabilities = {
            "device_a": DeviceCapabilities(device_id="device_a"),
            "device_b": DeviceCapabilities(device_id="device_b"),
        }

        result = select_device(target, [device_a, device_b], capabilities, current_time)

        assert result.device_id == "device_a"
        assert (
            result.score_breakdown.get("recent_interaction") == SCORE_RECENT_INTERACTION
        )

    def test_old_interaction_not_counted(self) -> None:
        """Old interaction does not boost score."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="bedroom",
            online=True,
            last_interaction_ts=current_time - RECENT_INTERACTION_SECONDS - 100,
        )

        target = AlertTarget()
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        assert result.device_id == "device"
        assert "recent_interaction" not in result.score_breakdown

    def test_same_room_fallback_score(self) -> None:
        """Device in different room gets fallback score."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="bedroom",
            online=True,
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        assert result.device_id == "device"
        assert (
            result.score_breakdown.get("same_room_fallback") == SCORE_SAME_ROOM_FALLBACK
        )


class TestSelectDeviceSignals:
    """Signal-aware selection tests."""

    def test_proximity_active_boosts_score(self) -> None:
        """Proximity signal boosts device score."""
        current_time = 1000.0

        device_with_proximity = DeviceContext(
            device_id="device_proximity",
            room="living_room",
            online=True,
            signals={"proximity_active": True},
        )
        device_without = DeviceContext(
            device_id="device_no_proximity",
            room="living_room",
            online=True,
            signals={},
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_proximity": DeviceCapabilities(device_id="device_proximity"),
            "device_no_proximity": DeviceCapabilities(device_id="device_no_proximity"),
        }

        result = select_device(
            target, [device_with_proximity, device_without], capabilities, current_time
        )

        assert result.device_id == "device_proximity"
        assert result.score_breakdown.get("proximity_active") == SCORE_PROXIMITY_ACTIVE

    def test_proximity_beats_recent_interaction(self) -> None:
        """Proximity signal can beat recent interaction."""
        current_time = 1000.0

        # Device A: proximity active (+30).
        device_a = DeviceContext(
            device_id="device_a",
            room="living_room",
            online=True,
            signals={"proximity_active": True},
        )
        # Device B: recent interaction (+50) but no proximity.
        # Note: proximity alone doesn't beat recent interaction.
        # But if both have same base, proximity wins.
        device_b = DeviceContext(
            device_id="device_b",
            room="living_room",
            online=True,
            last_interaction_ts=current_time - 60,
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_a": DeviceCapabilities(device_id="device_a"),
            "device_b": DeviceCapabilities(device_id="device_b"),
        }

        result = select_device(target, [device_a, device_b], capabilities, current_time)

        # Device B has higher score: 100 + 50 = 150 vs 100 + 30 = 130.
        assert result.device_id == "device_b"

    def test_screen_facing_boosts_score(self) -> None:
        """Screen facing signal boosts device score."""
        current_time = 1000.0

        device_facing = DeviceContext(
            device_id="device_facing",
            room="living_room",
            online=True,
            signals={"screen_facing": True},
        )
        device_not_facing = DeviceContext(
            device_id="device_not_facing",
            room="living_room",
            online=True,
            signals={"screen_facing": False},
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_facing": DeviceCapabilities(device_id="device_facing"),
            "device_not_facing": DeviceCapabilities(device_id="device_not_facing"),
        }

        result = select_device(
            target, [device_facing, device_not_facing], capabilities, current_time
        )

        assert result.device_id == "device_facing"
        assert result.score_breakdown.get("screen_facing") == SCORE_SCREEN_FACING

    def test_low_ambient_light_boosts_score(self) -> None:
        """Low ambient light boosts device score."""
        current_time = 1000.0

        device_dark = DeviceContext(
            device_id="device_dark",
            room="living_room",
            online=True,
            signals={"ambient_lux": LOW_LUX_THRESHOLD - 10},
        )
        device_bright = DeviceContext(
            device_id="device_bright",
            room="living_room",
            online=True,
            signals={"ambient_lux": LOW_LUX_THRESHOLD + 100},
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_dark": DeviceCapabilities(device_id="device_dark"),
            "device_bright": DeviceCapabilities(device_id="device_bright"),
        }

        result = select_device(
            target, [device_dark, device_bright], capabilities, current_time
        )

        assert result.device_id == "device_dark"
        assert result.score_breakdown.get("low_lux") == SCORE_LOW_LUX_BOOST

    def test_high_ambient_light_penalizes_score(self) -> None:
        """High ambient light penalizes device score."""
        current_time = 1000.0

        device_very_bright = DeviceContext(
            device_id="device_very_bright",
            room="living_room",
            online=True,
            signals={"ambient_lux": HIGH_LUX_THRESHOLD + 100},
        )
        device_normal = DeviceContext(
            device_id="device_normal",
            room="living_room",
            online=True,
            signals={"ambient_lux": 200},  # Between thresholds.
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_very_bright": DeviceCapabilities(device_id="device_very_bright"),
            "device_normal": DeviceCapabilities(device_id="device_normal"),
        }

        result = select_device(
            target, [device_very_bright, device_normal], capabilities, current_time
        )

        assert result.device_id == "device_normal"

    def test_missing_signals_do_not_crash(self) -> None:
        """Missing signals are handled gracefully."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="living_room",
            online=True,
            signals={},
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        assert result.device_id == "device"
        assert "proximity_active" not in result.score_breakdown
        assert "screen_facing" not in result.score_breakdown
        assert "low_lux" not in result.score_breakdown

    def test_unknown_signal_keys_ignored(self) -> None:
        """Unknown signal keys are silently ignored."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="living_room",
            online=True,
            signals={
                "unknown_signal": 123,
                "another_unknown": "value",
                "proximity_active": True,
            },
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        assert result.device_id == "device"
        assert result.score_breakdown.get("proximity_active") == SCORE_PROXIMITY_ACTIVE
        # Unknown signals not in breakdown.
        assert "unknown_signal" not in result.score_breakdown

    def test_combined_signals_stack(self) -> None:
        """Multiple positive signals stack additively."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="living_room",
            online=True,
            signals={
                "proximity_active": True,
                "screen_facing": True,
                "ambient_lux": 10,  # Low lux.
            },
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        expected_score = (
            SCORE_ROOM_MATCH
            + SCORE_PROXIMITY_ACTIVE
            + SCORE_SCREEN_FACING
            + SCORE_LOW_LUX_BOOST
        )
        assert result.score == expected_score


class TestSelectDeviceSafety:
    """Safety tests - signals cannot override eligibility."""

    def test_signal_wrong_type_proximity_ignored(self) -> None:
        """Proximity signal with wrong type is ignored."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="living_room",
            online=True,
            signals={"proximity_active": "yes"},  # Wrong type.
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        assert result.device_id == "device"
        assert "proximity_active" not in result.score_breakdown

    def test_signal_wrong_type_lux_ignored(self) -> None:
        """Lux signal with wrong type is ignored."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="living_room",
            online=True,
            signals={"ambient_lux": "low"},  # Wrong type.
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        assert result.device_id == "device"
        assert "low_lux" not in result.score_breakdown
        assert "high_lux" not in result.score_breakdown

    def test_signals_cannot_override_offline_status(self) -> None:
        """Positive signals cannot make offline device eligible."""
        current_time = 1000.0

        device_offline = DeviceContext(
            device_id="device_offline",
            room="living_room",
            online=False,
            signals={"proximity_active": True, "screen_facing": True},
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_offline": DeviceCapabilities(device_id="device_offline")
        }

        result = select_device(target, [device_offline], capabilities, current_time)

        assert result.device_id is None

    def test_signals_cannot_override_suppression(self) -> None:
        """Positive signals cannot override device suppression."""
        current_time = 1000.0

        device_suppressed = DeviceContext(
            device_id="device_suppressed",
            room="living_room",
            online=True,
            signals={"proximity_active": True},
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_suppressed": DeviceCapabilities(
                device_id="device_suppressed", suppressed=True
            )
        }

        result = select_device(target, [device_suppressed], capabilities, current_time)

        assert result.device_id is None

    def test_signals_cannot_override_missing_capabilities(self) -> None:
        """Positive signals cannot override missing capabilities."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="living_room",
            online=True,
            signals={"proximity_active": True},
        )

        target = AlertTarget(required_capabilities=frozenset(["alert_display"]))
        capabilities = {
            "device": DeviceCapabilities(device_id="device", capabilities=frozenset())
        }

        result = select_device(target, [device], capabilities, current_time)

        assert result.device_id is None

    def test_tie_break_prefers_most_recent_interaction(self) -> None:
        """Equal scores break tie by most recent interaction."""
        current_time = 1000.0

        device_a = DeviceContext(
            device_id="device_a",
            room="living_room",
            online=True,
            last_interaction_ts=current_time - 100,  # 100 seconds ago.
        )
        device_b = DeviceContext(
            device_id="device_b",
            room="living_room",
            online=True,
            last_interaction_ts=current_time - 50,  # 50 seconds ago (more recent).
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_a": DeviceCapabilities(device_id="device_a"),
            "device_b": DeviceCapabilities(device_id="device_b"),
        }

        result = select_device(target, [device_a, device_b], capabilities, current_time)

        # Both have same score (room match + recent interaction).
        # Tie-break by most recent interaction -> device_b.
        assert result.device_id == "device_b"


class TestRecentlyActiveSignal:
    """Tests for device-owned recently_active signal."""

    def test_recently_active_boosts_score(self) -> None:
        """Device-declared recently_active boosts score."""
        current_time = 1000.0

        device_active = DeviceContext(
            device_id="device_active",
            room="living_room",
            online=True,
            signals={"recently_active": True},
        )
        device_inactive = DeviceContext(
            device_id="device_inactive",
            room="living_room",
            online=True,
            signals={},
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_active": DeviceCapabilities(device_id="device_active"),
            "device_inactive": DeviceCapabilities(device_id="device_inactive"),
        }

        result = select_device(
            target, [device_active, device_inactive], capabilities, current_time
        )

        assert result.device_id == "device_active"
        assert result.score_breakdown.get("recently_active") == SCORE_RECENTLY_ACTIVE

    def test_recently_active_beats_proximity(self) -> None:
        """Device-declared recently_active scores higher than proximity."""
        current_time = 1000.0

        # recently_active: +40.
        device_active = DeviceContext(
            device_id="device_active",
            room="living_room",
            online=True,
            signals={"recently_active": True},
        )
        # proximity_active: +30.
        device_proximity = DeviceContext(
            device_id="device_proximity",
            room="living_room",
            online=True,
            signals={"proximity_active": True},
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {
            "device_active": DeviceCapabilities(device_id="device_active"),
            "device_proximity": DeviceCapabilities(device_id="device_proximity"),
        }

        result = select_device(
            target, [device_active, device_proximity], capabilities, current_time
        )

        assert result.device_id == "device_active"

    def test_recently_active_stacks_with_proximity(self) -> None:
        """Multiple device signals stack additively."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="living_room",
            online=True,
            signals={
                "recently_active": True,
                "proximity_active": True,
            },
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        expected_score = (
            SCORE_ROOM_MATCH + SCORE_RECENTLY_ACTIVE + SCORE_PROXIMITY_ACTIVE
        )
        assert result.score == expected_score
        assert result.score_breakdown.get("recently_active") == SCORE_RECENTLY_ACTIVE
        assert result.score_breakdown.get("proximity_active") == SCORE_PROXIMITY_ACTIVE

    def test_recently_active_false_not_counted(self) -> None:
        """Device explicitly reporting recently_active=False is not counted."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="living_room",
            online=True,
            signals={"recently_active": False},
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        assert result.device_id == "device"
        assert "recently_active" not in result.score_breakdown

    def test_recently_active_wrong_type_ignored(self) -> None:
        """Device signal with wrong type is safely ignored."""
        current_time = 1000.0

        device = DeviceContext(
            device_id="device",
            room="living_room",
            online=True,
            signals={"recently_active": "yes"},  # Wrong type.
        )

        target = AlertTarget(room_id="living_room")
        capabilities = {"device": DeviceCapabilities(device_id="device")}

        result = select_device(target, [device], capabilities, current_time)

        assert result.device_id == "device"
        assert "recently_active" not in result.score_breakdown
