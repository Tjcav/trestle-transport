"""Tests for decision trace module.

Slice: 8i - Decision Tracing & Explainability
"""

import json
from datetime import datetime

from trestle_coordinator_core.trace import (
    ArbitrationTrace,
    CompetingIntent,
    ConditionCheck,
    DecisionOutcome,
    DecisionTrace,
    DomainSnapshot,
    DomainStateEntry,
    FusionContribution,
    IntentClassification,
    OutcomeType,
    PanelDelivery,
    PerformanceMetrics,
    PolicyEvaluationTrace,
    QuietHoursCheck,
    RuleEvaluation,
    RuleResult,
    SignalContribution,
    Trigger,
    TriggerType,
    WinningIntent,
)


class TestTrigger:
    """Tests for Trigger dataclass."""

    def test_state_change_trigger(self) -> None:
        """Test creating a state change trigger."""
        trigger = Trigger(
            type=TriggerType.STATE_CHANGE,
            domain="security",
            scope_id="front_door",
            previous_state="idle",
            new_state="door_open",
            source="binary_sensor.front_door",
        )

        assert trigger.type == TriggerType.STATE_CHANGE
        assert trigger.domain == "security"
        assert trigger.scope_id == "front_door"
        assert trigger.previous_state == "idle"
        assert trigger.new_state == "door_open"

    def test_event_trigger(self) -> None:
        """Test creating an event trigger."""
        trigger = Trigger(
            type=TriggerType.EVENT,
            domain="doorbell",
            event="ring",
        )

        assert trigger.type == TriggerType.EVENT
        assert trigger.event == "ring"


class TestDomainSnapshot:
    """Tests for domain snapshot."""

    def test_empty_snapshot(self) -> None:
        """Test snapshot with no domains."""
        snapshot = DomainSnapshot(
            domains=[],
            snapshot_time=datetime.now(),
        )

        assert len(snapshot.domains) == 0
        assert len(snapshot.active_effects) == 0

    def test_snapshot_with_fusion(self) -> None:
        """Test snapshot with fusion contribution."""
        fusion = FusionContribution(
            signals=[
                SignalContribution(
                    signal_source="binary_sensor.motion",
                    signal_type="motion",
                    weight=0.8,
                    decay_factor=0.9,
                )
            ],
            confidence=0.92,
        )

        domain = DomainStateEntry(
            domain="occupancy",
            state="home",
            scope_id="living_room",
            fusion=fusion,
        )

        snapshot = DomainSnapshot(
            domains=[domain],
            snapshot_time=datetime.now(),
            time_of_day="14:30",
        )

        assert len(snapshot.domains) == 1
        assert snapshot.domains[0].fusion is not None
        assert snapshot.domains[0].fusion.confidence == 0.92


class TestRuleEvaluation:
    """Tests for rule evaluation trace."""

    def test_matched_rule(self) -> None:
        """Test a rule that matched."""
        rule = RuleEvaluation(
            rule_id="door-open-notify",
            result=RuleResult.MATCHED,
            when_clause=ConditionCheck(
                condition_type="when",
                domain="security",
                expected="door_open",
                actual="door_open",
                satisfied=True,
            ),
            classification=IntentClassification(
                importance="high",
                interrupt=True,
            ),
        )

        assert rule.result == RuleResult.MATCHED
        assert rule.when_clause.satisfied
        assert rule.classification.importance == "high"

    def test_skipped_rule(self) -> None:
        """Test a rule that was skipped."""
        rule = RuleEvaluation(
            rule_id="laundry-done",
            result=RuleResult.SKIPPED,
            when_clause=ConditionCheck(
                condition_type="when",
                domain="laundry",
                expected="done",
                actual="running",
                satisfied=False,
            ),
            skip_reason="when clause not satisfied",
        )

        assert rule.result == RuleResult.SKIPPED
        assert not rule.when_clause.satisfied
        assert rule.skip_reason == "when clause not satisfied"

    def test_suppressed_rule(self) -> None:
        """Test a rule that matched but was suppressed."""
        rule = RuleEvaluation(
            rule_id="laundry-done",
            result=RuleResult.SUPPRESSED,
            when_clause=ConditionCheck(
                condition_type="when",
                domain="laundry",
                expected="done",
                actual="done",
                satisfied=True,
            ),
            suppress_if_checks=[
                ConditionCheck(
                    condition_type="suppress_if",
                    domain="sleep",
                    expected="asleep",
                    actual="asleep",
                    satisfied=True,
                )
            ],
            classification=IntentClassification(importance="low"),
            suppress_reason="sleep state active",
        )

        assert rule.result == RuleResult.SUPPRESSED
        assert rule.suppress_reason == "sleep state active"


class TestDecisionTrace:
    """Tests for complete decision trace."""

    def test_create_trace(self) -> None:
        """Test trace creation helper."""
        trigger = Trigger(
            type=TriggerType.STATE_CHANGE,
            domain="security",
        )
        snapshot = DomainSnapshot(
            domains=[],
            snapshot_time=datetime.now(),
        )

        trace = DecisionTrace.create(
            profile_id="test-profile",
            trigger=trigger,
            domain_snapshot=snapshot,
        )

        assert trace.trace_id  # UUID generated
        assert trace.timestamp  # Timestamp set
        assert trace.profile_id == "test-profile"
        assert trace.outcome.type == OutcomeType.NO_ACTION

    def test_complete_trace(self) -> None:
        """Test a complete decision trace."""
        trace = DecisionTrace(
            trace_id="test-trace-id",
            timestamp=datetime(2025, 1, 15, 22, 35, 42),
            profile_id="home-family",
            profile_version="1.0.0",
            home_id="home-123",
            trigger=Trigger(
                type=TriggerType.STATE_CHANGE,
                domain="security",
                scope_id="front_door",
                previous_state="idle",
                new_state="door_open",
            ),
            domain_snapshot=DomainSnapshot(
                domains=[
                    DomainStateEntry(
                        domain="security",
                        state="door_open",
                        scope_id="front_door",
                    ),
                    DomainStateEntry(
                        domain="occupancy",
                        state="away",
                        scope_id="house",
                    ),
                ],
                snapshot_time=datetime(2025, 1, 15, 22, 35, 42),
                time_of_day="22:35",
            ),
            policy_trace=PolicyEvaluationTrace(
                rules=[
                    RuleEvaluation(
                        rule_id="door-while-away",
                        result=RuleResult.MATCHED,
                        classification=IntentClassification(
                            importance="critical",
                            interrupt=True,
                            bypass_quiet_hours=True,
                        ),
                    )
                ],
                quiet_hours=QuietHoursCheck(
                    configured=True,
                    start_time="23:00",
                    end_time="07:00",
                    currently_active=False,
                    current_time="22:35",
                ),
                rules_evaluated=1,
                rules_matched=1,
            ),
            outcome=DecisionOutcome(
                type=OutcomeType.ALERT_DELIVERED,
                intent=WinningIntent(
                    domain="security",
                    rule_id="door-while-away",
                    importance="critical",
                    interrupt=True,
                    scope_id="front_door",
                ),
                arbitration=ArbitrationTrace(
                    candidates=[
                        CompetingIntent(
                            rule_id="door-while-away",
                            importance="critical",
                            interrupt=True,
                            selected=True,
                        )
                    ],
                    selection_reason="single matching rule",
                ),
                delivery=PanelDelivery(
                    delivered=True,
                    target_panels=["panel-kitchen"],
                    audible=True,
                    haptic=True,
                    visual_urgency="urgent",
                ),
            ),
            metrics=PerformanceMetrics(
                total_duration_us=1250,
                policy_duration_us=680,
                rules_evaluated=1,
            ),
        )

        assert trace.outcome.type == OutcomeType.ALERT_DELIVERED
        assert trace.outcome.intent.importance == "critical"
        assert trace.outcome.delivery.delivered

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        trace = DecisionTrace.create(
            profile_id="test-profile",
            trigger=Trigger(
                type=TriggerType.STATE_CHANGE,
                domain="security",
            ),
            domain_snapshot=DomainSnapshot(
                domains=[],
                snapshot_time=datetime(2025, 1, 15, 12, 0, 0),
            ),
        )

        data = trace.to_dict()

        assert data["profile_id"] == "test-profile"
        assert data["trigger"]["type"] == "state_change"
        assert data["trigger"]["domain"] == "security"
        assert data["outcome"]["type"] == "no_action"

        # Should be JSON serializable
        json_str = json.dumps(data)
        assert json_str


class TestOutcomeTypes:
    """Tests for different outcome types."""

    def test_no_action_outcome(self) -> None:
        """Test no action outcome."""
        outcome = DecisionOutcome(type=OutcomeType.NO_ACTION)
        assert outcome.type == OutcomeType.NO_ACTION
        assert outcome.intent is None

    def test_suppressed_outcome(self) -> None:
        """Test suppressed outcome."""
        outcome = DecisionOutcome(
            type=OutcomeType.SUPPRESSED,
            delivery=PanelDelivery(
                delivered=False,
                skip_reason="quiet hours active",
            ),
        )
        assert outcome.type == OutcomeType.SUPPRESSED
        assert not outcome.delivery.delivered

    def test_delivered_outcome(self) -> None:
        """Test delivered outcome."""
        outcome = DecisionOutcome(
            type=OutcomeType.ALERT_DELIVERED,
            intent=WinningIntent(
                domain="security",
                rule_id="test-rule",
                importance="high",
            ),
            delivery=PanelDelivery(
                delivered=True,
                target_panels=["panel-1", "panel-2"],
            ),
        )
        assert outcome.type == OutcomeType.ALERT_DELIVERED
        assert outcome.delivery.delivered
        assert len(outcome.delivery.target_panels) == 2
