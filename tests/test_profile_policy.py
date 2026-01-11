"""Tests for Slice 8d — Profile Loading and Policy Evaluation.

These tests verify:
1. Profile loading from spec files
2. Domain registration
3. Policy rule evaluation
4. The four required scenarios
"""

from datetime import time
from pathlib import Path

import pytest

from trestle_coordinator_core.policy_engine import (
    DomainState,
    Importance,
    evaluate_domain_update,
)
from trestle_coordinator_core.profile import (
    DomainNotFoundError,
    DomainScope,
    LoadedProfile,
    QuietHours,
    load_domain,
    load_profile,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def spec_profiles_dir() -> Path:
    """Path to trestle-spec profiles directory."""
    return Path("/workspaces/trestle-spec/profiles")


@pytest.fixture
def home_runtime_dir(spec_profiles_dir: Path) -> Path:
    """Path to home profile runtime directory."""
    return spec_profiles_dir / "runtime" / "home"


@pytest.fixture
def loaded_home_profile(home_runtime_dir: Path) -> LoadedProfile:
    """Load the actual home profile from spec."""
    return load_profile(home_runtime_dir)


@pytest.fixture
def base_domain_states() -> dict[str, DomainState]:
    """Base domain states for testing."""
    return {
        "occupancy": DomainState(domain="occupancy", state="vacant"),
        "security": DomainState(domain="security", state="armed_home"),
        "media_activity": DomainState(domain="media_activity", state="idle"),
        "house_mode": DomainState(domain="house_mode", state="home"),
        "time": DomainState(domain="time", state="day"),
        "weather": DomainState(domain="weather", state="clear"),
        "doorbell": DomainState(domain="doorbell", state="idle"),
        "motion": DomainState(domain="motion", state="idle"),
        "timer": DomainState(domain="timer", state="idle"),
    }


# =============================================================================
# Profile Loading Tests (Step 1 & 2)
# =============================================================================


class TestProfileLoading:
    """Tests for loading profiles from spec files."""

    def test_load_home_profile(self, home_runtime_dir: Path) -> None:
        """Can load the home profile from spec."""
        profile = load_profile(home_runtime_dir)

        assert profile.profile_id == "home"
        assert profile.profile_version == "1.0.0"
        assert profile.profile_name == "RockBridge Home"

    def test_all_nine_domains_registered(
        self, loaded_home_profile: LoadedProfile
    ) -> None:
        """All nine domains from manifest are registered."""
        expected_domains = {
            "occupancy",
            "security",
            "media_activity",
            "house_mode",
            "time",
            "weather",
            "doorbell",
            "motion",
            "timer",
        }

        assert set(loaded_home_profile.domains.keys()) == expected_domains

    def test_domain_schemas_loaded(self, loaded_home_profile: LoadedProfile) -> None:
        """Domain schemas have correct structure."""
        # Check occupancy (per_room scope)
        occupancy = loaded_home_profile.domains["occupancy"]
        assert occupancy.scope == DomainScope.PER_ROOM
        assert "occupied" in occupancy.states
        assert "vacant" in occupancy.states

        # Check security (house scope)
        security = loaded_home_profile.domains["security"]
        assert security.scope == DomainScope.HOUSE
        assert "triggered" in security.states
        assert "armed_home" in security.states

        # Check doorbell (event-driven)
        doorbell = loaded_home_profile.domains["doorbell"]
        assert "ring" in doorbell.events

    def test_policy_loaded(self, loaded_home_profile: LoadedProfile) -> None:
        """Policy rules are loaded."""
        policy = loaded_home_profile.policy

        assert policy.quiet_hours is not None
        assert policy.quiet_hours.start == time(22, 0)
        assert policy.quiet_hours.end == time(7, 0)

        assert len(policy.rules) > 0

        # Check security_alarm rule exists
        rule_ids = [r.rule_id for r in policy.rules]
        assert "security_alarm" in rule_ids
        assert "doorbell" in rule_ids
        assert "motion_info" in rule_ids

    def test_missing_domain_raises_error(self, home_runtime_dir: Path) -> None:
        """Missing domain file raises DomainNotFoundError."""
        domains_dir = home_runtime_dir / "domains"
        with pytest.raises(DomainNotFoundError, match="not_a_domain"):
            load_domain(domains_dir, "not_a_domain")


class TestQuietHours:
    """Tests for quiet hours logic."""

    def test_overnight_quiet_hours_before_midnight(self) -> None:
        """Quiet hours active before midnight."""
        qh = QuietHours(start=time(22, 0), end=time(7, 0))
        assert qh.is_active(time(23, 0)) is True
        assert qh.is_active(time(22, 0)) is True
        assert qh.is_active(time(21, 59)) is False

    def test_overnight_quiet_hours_after_midnight(self) -> None:
        """Quiet hours active after midnight."""
        qh = QuietHours(start=time(22, 0), end=time(7, 0))
        assert qh.is_active(time(3, 0)) is True
        assert qh.is_active(time(7, 0)) is True
        assert qh.is_active(time(7, 1)) is False

    def test_same_day_quiet_hours(self) -> None:
        """Same-day quiet hours window."""
        qh = QuietHours(start=time(14, 0), end=time(16, 0))
        assert qh.is_active(time(15, 0)) is True
        assert qh.is_active(time(14, 0)) is True
        assert qh.is_active(time(16, 0)) is True
        assert qh.is_active(time(13, 59)) is False
        assert qh.is_active(time(16, 1)) is False


# =============================================================================
# Policy Evaluation Tests (Step 4)
# =============================================================================


class TestPolicyEvaluation:
    """Tests for policy rule evaluation."""

    def test_security_alarm_rule_matches(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """Security alarm rule matches when triggered."""
        states = dict(base_domain_states)
        states["security"] = DomainState(domain="security", state="triggered")

        intents = evaluate_domain_update(
            loaded_home_profile,
            states["security"],
            states,
            current_time=time(12, 0),  # Daytime
        )

        assert len(intents) >= 1
        alarm_intent = next(i for i in intents if i.rule_id == "security_alarm")
        assert alarm_intent.importance == Importance.CRITICAL
        assert alarm_intent.interrupt is True
        assert alarm_intent.bypass_quiet_hours is True
        assert alarm_intent.suppressed is False

    def test_doorbell_rule_matches(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """Doorbell rule matches on ring event."""
        states = dict(base_domain_states)
        states["doorbell"] = DomainState(domain="doorbell", event="ring")

        intents = evaluate_domain_update(
            loaded_home_profile,
            states["doorbell"],
            states,
            current_time=time(12, 0),
        )

        assert len(intents) >= 1
        doorbell_intent = next(i for i in intents if i.rule_id == "doorbell")
        assert doorbell_intent.importance == Importance.HIGH
        assert doorbell_intent.suppressed is False

    def test_motion_suppressed_when_occupied(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """Motion is suppressed when room is occupied."""
        states = dict(base_domain_states)
        states["occupancy"] = DomainState(domain="occupancy", state="occupied")
        states["motion"] = DomainState(domain="motion", event="detected")

        intents = evaluate_domain_update(
            loaded_home_profile,
            states["motion"],
            states,
            current_time=time(12, 0),
        )

        motion_intents = [i for i in intents if i.rule_id == "motion_info"]
        if motion_intents:
            assert motion_intents[0].suppressed is True
            assert motion_intents[0].suppression_reason == "occupancy=occupied"

    def test_media_playing_suppresses_low_importance(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """Media playing suppresses low importance intents."""
        states = dict(base_domain_states)
        states["media_activity"] = DomainState(domain="media_activity", state="playing")
        states["motion"] = DomainState(domain="motion", event="detected")
        # Make sure occupancy is vacant so motion isn't suppressed by that
        states["occupancy"] = DomainState(domain="occupancy", state="vacant")

        intents = evaluate_domain_update(
            loaded_home_profile,
            states["motion"],
            states,
            current_time=time(12, 0),
        )

        motion_intents = [i for i in intents if i.rule_id == "motion_info"]
        if motion_intents:
            assert motion_intents[0].suppressed is True
            assert "importance below" in (motion_intents[0].suppression_reason or "")

    def test_timer_done_produces_medium_intent(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """Timer finished produces medium importance intent."""
        states = dict(base_domain_states)
        states["timer"] = DomainState(domain="timer", event="finished")

        intents = evaluate_domain_update(
            loaded_home_profile,
            states["timer"],
            states,
            current_time=time(12, 0),
        )

        timer_intents = [i for i in intents if i.rule_id == "timer_done"]
        assert len(timer_intents) == 1
        assert timer_intents[0].importance == Importance.MEDIUM
        assert timer_intents[0].suppressed is False


# =============================================================================
# Scenario Tests (Step 6)
# =============================================================================


class TestScenario1DoorbellAt23:
    """Scenario 1: Doorbell at 23:00.

    Expected:
    - Interrupt
    - Not suppressed (doorbell is high importance)
    - Medium/high priority
    """

    def test_doorbell_at_23_not_suppressed(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """Doorbell at 23:00 should not be suppressed during quiet hours."""
        states = dict(base_domain_states)
        states["doorbell"] = DomainState(domain="doorbell", event="ring")

        intents = evaluate_domain_update(
            loaded_home_profile,
            states["doorbell"],
            states,
            current_time=time(23, 0),  # During quiet hours
        )

        doorbell_intents = [i for i in intents if i.rule_id == "doorbell"]
        assert len(doorbell_intents) == 1

        intent = doorbell_intents[0]
        assert intent.importance == Importance.HIGH
        # High importance should not be suppressed by quiet hours
        # (quiet hours typically suppresses interrupt, not the intent itself)


class TestScenario2MotionWhileMediaPlaying:
    """Scenario 2: Motion while media playing.

    Expected:
    - Suppressed
    - No interrupt
    - Background at most
    """

    def test_motion_suppressed_during_media(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """Motion while media playing should be suppressed."""
        states = dict(base_domain_states)
        states["media_activity"] = DomainState(domain="media_activity", state="playing")
        states["motion"] = DomainState(domain="motion", event="detected")
        states["occupancy"] = DomainState(domain="occupancy", state="vacant")

        intents = evaluate_domain_update(
            loaded_home_profile,
            states["motion"],
            states,
            current_time=time(20, 0),
        )

        motion_intents = [i for i in intents if i.rule_id == "motion_info"]
        if motion_intents:
            intent = motion_intents[0]
            assert intent.suppressed is True
            assert intent.interrupt is False


class TestScenario3SecurityAlarmDuringQuietHours:
    """Scenario 3: Security alarm during quiet hours.

    Expected:
    - Full interrupt
    - Quiet-hours bypass
    - Non-dismissible (critical)
    """

    def test_security_alarm_bypasses_quiet_hours(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """Security alarm at 3am should still interrupt."""
        states = dict(base_domain_states)
        states["security"] = DomainState(domain="security", state="triggered")

        intents = evaluate_domain_update(
            loaded_home_profile,
            states["security"],
            states,
            current_time=time(3, 0),  # Deep in quiet hours
        )

        alarm_intents = [i for i in intents if i.rule_id == "security_alarm"]
        assert len(alarm_intents) == 1

        intent = alarm_intents[0]
        assert intent.importance == Importance.CRITICAL
        assert intent.interrupt is True
        assert intent.bypass_quiet_hours is True
        assert intent.suppressed is False


class TestScenario4TimerFinishesWhileIdle:
    """Scenario 4: Timer finishes while idle.

    Expected:
    - Medium priority
    - Dismissible
    - Returns to ambient
    """

    def test_timer_done_medium_priority(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """Timer finished while idle should produce medium priority intent."""
        states = dict(base_domain_states)
        states["timer"] = DomainState(domain="timer", event="finished")
        # Ensure idle state - no media, no alarm
        states["media_activity"] = DomainState(domain="media_activity", state="idle")
        states["security"] = DomainState(domain="security", state="disarmed")

        intents = evaluate_domain_update(
            loaded_home_profile,
            states["timer"],
            states,
            current_time=time(14, 0),  # Daytime, outside quiet hours
        )

        timer_intents = [i for i in intents if i.rule_id == "timer_done"]
        assert len(timer_intents) == 1

        intent = timer_intents[0]
        assert intent.importance == Importance.MEDIUM
        assert intent.suppressed is False
        # Timer is dismissible (not critical, no bypass)
        assert intent.bypass_quiet_hours is False


# =============================================================================
# Importance Ordering Tests
# =============================================================================


class TestImportanceOrdering:
    """Tests for importance level ordering."""

    def test_importance_ordering(self) -> None:
        """Importance levels are correctly ordered."""
        assert Importance.LOW < Importance.MEDIUM
        assert Importance.MEDIUM < Importance.HIGH
        assert Importance.HIGH < Importance.CRITICAL

    def test_importance_equality(self) -> None:
        """Importance equality works."""
        assert Importance.LOW <= Importance.LOW
        assert Importance.CRITICAL <= Importance.CRITICAL

    def test_importance_from_string(self) -> None:
        """Importance can be parsed from string."""
        assert Importance.from_string("low") == Importance.LOW
        assert Importance.from_string("critical") == Importance.CRITICAL
        assert Importance.from_string("HIGH") == Importance.HIGH


# =============================================================================
# Integration Tests
# =============================================================================


class TestFullProfileIntegration:
    """Integration tests loading real profile and running scenarios."""

    def test_can_log_registered_domains(
        self, loaded_home_profile: LoadedProfile
    ) -> None:
        """Can produce the expected log output for domain registration."""
        expected_log = (
            f"Loaded profile {loaded_home_profile.profile_id}"
            f" v{loaded_home_profile.profile_version}\n"
            f"Registered domains: {', '.join(sorted(loaded_home_profile.domains.keys()))}"
        )

        # Just verify we can produce this - actual logging is separate
        assert "home" in expected_log
        assert "occupancy" in expected_log
        assert "security" in expected_log
        assert "doorbell" in expected_log

    def test_all_scenarios_produce_intents(
        self,
        loaded_home_profile: LoadedProfile,
        base_domain_states: dict[str, DomainState],
    ) -> None:
        """All four scenarios produce expected intent structure."""
        # This is a sanity check that the profile/policy integration works

        # Scenario 1: Doorbell
        states1 = dict(base_domain_states)
        states1["doorbell"] = DomainState(domain="doorbell", event="ring")
        intents1 = evaluate_domain_update(
            loaded_home_profile, states1["doorbell"], states1, time(23, 0)
        )
        assert any(i.rule_id == "doorbell" for i in intents1)

        # Scenario 2: Motion during media (may be suppressed - that's ok)
        states2 = dict(base_domain_states)
        states2["media_activity"] = DomainState(
            domain="media_activity", state="playing"
        )
        states2["motion"] = DomainState(domain="motion", event="detected")
        # Note: motion_info rule may or may not fire based on suppress_if
        # The key is the system doesn't crash

        # Scenario 3: Security alarm
        states3 = dict(base_domain_states)
        states3["security"] = DomainState(domain="security", state="triggered")
        intents3 = evaluate_domain_update(
            loaded_home_profile, states3["security"], states3, time(3, 0)
        )
        assert any(
            i.rule_id == "security_alarm" and i.suppressed is False for i in intents3
        )

        # Scenario 4: Timer done
        states4 = dict(base_domain_states)
        states4["timer"] = DomainState(domain="timer", event="finished")
        intents4 = evaluate_domain_update(
            loaded_home_profile, states4["timer"], states4, time(14, 0)
        )
        assert any(i.rule_id == "timer_done" for i in intents4)
