"""Tests for trace emission (Slice 8i-2)."""

from datetime import datetime, time

from trestle_coordinator_core.policy_engine import (
    DomainState,
    EvaluationContext,
    Importance,
    IntentCandidate,
)
from trestle_coordinator_core.profile import (
    PolicyClassification,
    PolicyCondition,
    PolicyRule,
)
from trestle_coordinator_core.trace import (
    DecisionOutcome,
    DomainSnapshot,
    DomainStateEntry,
    OutcomeType,
    RuleResult,
    Trigger,
    TriggerType,
)
from trestle_coordinator_core.trace_emitter import (
    BufferEmitter,
    CallbackEmitter,
    NullEmitter,
    TraceBuilder,
    TraceConfig,
    build_domain_snapshot,
    build_trigger_from_state,
    determine_outcome,
    trace_rule_evaluation,
)


class TestTraceConfig:
    """Tests for trace configuration."""

    def test_disabled_by_default(self) -> None:
        """Tracing should be disabled by default."""
        config = TraceConfig()
        assert not config.enabled
        assert not config.should_trace()

    def test_enabled_always_traces(self) -> None:
        """When enabled with 1.0 sample rate, always trace."""
        config = TraceConfig(enabled=True, sample_rate=1.0)
        # Should always return True
        for _ in range(100):
            assert config.should_trace()

    def test_sampling(self) -> None:
        """Sampling should work approximately correctly."""
        config = TraceConfig(enabled=True, sample_rate=0.5)
        traces = sum(1 for _ in range(1000) if config.should_trace())
        # Should be roughly 50%, allow wide margin
        assert 300 < traces < 700

    def test_zero_sample_rate(self) -> None:
        """Zero sample rate should never trace."""
        config = TraceConfig(enabled=True, sample_rate=0.0)
        for _ in range(100):
            assert not config.should_trace()


class TestEmitters:
    """Tests for trace emitters."""

    def test_null_emitter(self) -> None:
        """NullEmitter should discard traces."""
        emitter = NullEmitter()
        trace = _create_minimal_trace()
        # Should not raise
        emitter.emit(trace)

    def test_buffer_emitter_stores_traces(self) -> None:
        """BufferEmitter should store traces."""
        emitter = BufferEmitter(max_size=10)
        trace = _create_minimal_trace()

        emitter.emit(trace)

        assert len(emitter.traces) == 1
        assert emitter.traces[0] == trace

    def test_buffer_emitter_evicts_oldest(self) -> None:
        """BufferEmitter should evict oldest when full."""
        emitter = BufferEmitter(max_size=3)

        for i in range(5):
            trace = _create_minimal_trace()
            trace.profile_id = f"profile-{i}"
            emitter.emit(trace)

        assert len(emitter.traces) == 3
        # Oldest (0, 1) should be evicted
        assert emitter.traces[0].profile_id == "profile-2"
        assert emitter.traces[2].profile_id == "profile-4"

    def test_buffer_emitter_last(self) -> None:
        """BufferEmitter.last() should return last N traces."""
        emitter = BufferEmitter()

        for i in range(5):
            trace = _create_minimal_trace()
            trace.profile_id = f"profile-{i}"
            emitter.emit(trace)

        last_two = emitter.last(2)
        assert len(last_two) == 2
        assert last_two[0].profile_id == "profile-3"
        assert last_two[1].profile_id == "profile-4"

    def test_callback_emitter(self) -> None:
        """CallbackEmitter should call the callback."""
        received: list = []
        emitter = CallbackEmitter(lambda t: received.append(t))

        trace = _create_minimal_trace()
        emitter.emit(trace)

        assert len(received) == 1
        assert received[0] == trace


class TestTraceBuilder:
    """Tests for building traces."""

    def test_minimal_trace(self) -> None:
        """Build a minimal trace."""
        trigger = Trigger(type=TriggerType.STATE_CHANGE, domain="security")
        snapshot = DomainSnapshot(domains=[], snapshot_time=datetime.now())

        builder = TraceBuilder(
            profile_id="test-profile",
            profile_version="1.0.0",
            home_id="home-123",
            trigger=trigger,
            domain_snapshot=snapshot,
        )

        trace = builder.build()

        assert trace.profile_id == "test-profile"
        assert trace.profile_version == "1.0.0"
        assert trace.home_id == "home-123"
        assert trace.outcome.type == OutcomeType.NO_ACTION

    def test_trace_with_decision_id(self) -> None:
        """Trace should include decision ID for lineage."""
        trigger = Trigger(type=TriggerType.STATE_CHANGE, domain="security")
        snapshot = DomainSnapshot(domains=[], snapshot_time=datetime.now())

        builder = TraceBuilder(
            profile_id="test-profile",
            profile_version=None,
            home_id=None,
            trigger=trigger,
            domain_snapshot=snapshot,
        )
        builder.set_decision_id("home-123:security:001", "home-123:security:000")

        trace = builder.build()

        assert trace.decision_id == "home-123:security:001"
        assert trace.parent_decision_id == "home-123:security:000"

    def test_trace_with_rule_evaluations(self) -> None:
        """Trace should accumulate rule evaluations."""
        trigger = Trigger(type=TriggerType.STATE_CHANGE, domain="security")
        snapshot = DomainSnapshot(domains=[], snapshot_time=datetime.now())

        builder = TraceBuilder(
            profile_id="test-profile",
            profile_version=None,
            home_id=None,
            trigger=trigger,
            domain_snapshot=snapshot,
        )

        builder.add_rule_evaluation(
            rule_id="rule-1",
            result=RuleResult.MATCHED,
        )
        builder.add_rule_evaluation(
            rule_id="rule-2",
            result=RuleResult.SKIPPED,
            failed_conditions=["occupancy == home"],
            skip_reason="condition not met",
        )

        trace = builder.build()

        assert trace.policy_trace.rules_evaluated == 2
        assert trace.policy_trace.rules_matched == 1
        assert trace.policy_trace.rules_skipped == 1

    def test_trace_includes_metrics(self) -> None:
        """Trace should include timing metrics when enabled."""
        trigger = Trigger(type=TriggerType.STATE_CHANGE, domain="security")
        snapshot = DomainSnapshot(
            domains=[
                DomainStateEntry(domain="security", state="alert"),
                DomainStateEntry(domain="occupancy", state="away"),
            ],
            snapshot_time=datetime.now(),
        )

        builder = TraceBuilder(
            profile_id="test-profile",
            profile_version=None,
            home_id=None,
            trigger=trigger,
            domain_snapshot=snapshot,
            config=TraceConfig(enabled=True, include_metrics=True),
        )

        builder.start_policy_evaluation()
        builder.add_rule_evaluation(rule_id="rule-1", result=RuleResult.MATCHED)
        builder.end_policy_evaluation()

        trace = builder.build()

        assert trace.metrics is not None
        assert trace.metrics.domains_evaluated == 2
        assert trace.metrics.rules_evaluated == 1
        assert trace.metrics.total_duration_us >= 0

    def test_trace_without_metrics(self) -> None:
        """Trace should omit metrics when disabled."""
        trigger = Trigger(type=TriggerType.STATE_CHANGE, domain="security")
        snapshot = DomainSnapshot(domains=[], snapshot_time=datetime.now())

        builder = TraceBuilder(
            profile_id="test-profile",
            profile_version=None,
            home_id=None,
            trigger=trigger,
            domain_snapshot=snapshot,
            config=TraceConfig(enabled=True, include_metrics=False),
        )

        trace = builder.build()

        assert trace.metrics is None


class TestHelperFunctions:
    """Tests for trace building helper functions."""

    def test_build_trigger_from_state(self) -> None:
        """Build trigger from domain state change."""
        state = DomainState(
            domain="security",
            state="door_open",
            scope_id="front_door",
            metadata={"entity_id": "binary_sensor.front_door"},
        )

        trigger = build_trigger_from_state(state, previous_state="idle")

        assert trigger.type == TriggerType.STATE_CHANGE
        assert trigger.domain == "security"
        assert trigger.scope_id == "front_door"
        assert trigger.previous_state == "idle"
        assert trigger.new_state == "door_open"
        assert trigger.source == "binary_sensor.front_door"

    def test_build_domain_snapshot(self) -> None:
        """Build snapshot from domain states."""
        states = {
            "security": DomainState(
                domain="security", state="alert", scope_id="front_door"
            ),
            "occupancy": DomainState(
                domain="occupancy", state="away", scope_id="house"
            ),
        }

        snapshot = build_domain_snapshot(states, current_time="22:30")

        assert len(snapshot.domains) == 2
        assert snapshot.time_of_day == "22:30"

    def test_determine_outcome_no_intents(self) -> None:
        """No intents means no action."""
        outcome_type, winner = determine_outcome([])
        assert outcome_type == OutcomeType.NO_ACTION
        assert winner is None

    def test_determine_outcome_all_suppressed(self) -> None:
        """All suppressed intents means suppressed outcome."""
        intents = [
            IntentCandidate(
                domain="laundry",
                rule_id="laundry-done",
                importance=Importance.LOW,
                suppressed=True,
                suppression_reason="quiet_hours",
            )
        ]

        outcome_type, winner = determine_outcome(intents)
        assert outcome_type == OutcomeType.SUPPRESSED
        assert winner is None

    def test_determine_outcome_picks_highest_importance(self) -> None:
        """Winner should be highest importance intent."""
        intents = [
            IntentCandidate(
                domain="laundry",
                rule_id="laundry-done",
                importance=Importance.LOW,
            ),
            IntentCandidate(
                domain="security",
                rule_id="door-open",
                importance=Importance.CRITICAL,
                interrupt=True,
            ),
            IntentCandidate(
                domain="weather",
                rule_id="rain-alert",
                importance=Importance.MEDIUM,
            ),
        ]

        outcome_type, winner = determine_outcome(intents)

        assert outcome_type == OutcomeType.INTENT_GENERATED
        assert winner is not None
        assert winner.domain == "security"
        assert winner.importance == "critical"
        assert winner.interrupt


class TestRuleEvaluationTracing:
    """Tests for tracing rule evaluation."""

    def test_trace_matched_rule(self) -> None:
        """Trace a rule that matched."""
        rule = PolicyRule(
            rule_id="door-alert",
            when=PolicyCondition(domain="security", state="door_open"),
            classify=PolicyClassification(importance="high", interrupt=True),
        )
        state = DomainState(domain="security", state="door_open")
        context = EvaluationContext(
            domain_states={"security": state},
            current_time=time(22, 30),
        )
        intent = IntentCandidate(
            domain="security",
            rule_id="door-alert",
            importance=Importance.HIGH,
            interrupt=True,
        )

        evaluation = trace_rule_evaluation(rule, state, context, intent)

        assert evaluation.rule_id == "door-alert"
        assert evaluation.result == RuleResult.MATCHED
        assert evaluation.when_clause is not None
        assert evaluation.when_clause.satisfied
        assert len(evaluation.failed_conditions) == 0

    def test_trace_skipped_rule_when_clause(self) -> None:
        """Trace a rule skipped because when clause didn't match."""
        rule = PolicyRule(
            rule_id="door-alert",
            when=PolicyCondition(domain="security", state="door_open"),
            classify=PolicyClassification(importance="high"),
        )
        state = DomainState(domain="security", state="idle")
        context = EvaluationContext(
            domain_states={"security": state},
            current_time=time(22, 30),
        )

        evaluation = trace_rule_evaluation(rule, state, context, None)

        assert evaluation.result == RuleResult.SKIPPED
        assert not evaluation.when_clause.satisfied
        assert "security == door_open" in evaluation.failed_conditions

    def test_trace_skipped_rule_conditions(self) -> None:
        """Trace a rule skipped because conditions didn't match."""
        rule = PolicyRule(
            rule_id="door-alert-away",
            when=PolicyCondition(domain="security", state="door_open"),
            conditions={"occupancy": "away"},
            classify=PolicyClassification(importance="critical"),
        )
        state = DomainState(domain="security", state="door_open")
        context = EvaluationContext(
            domain_states={
                "security": state,
                "occupancy": DomainState(domain="occupancy", state="home"),
            },
            current_time=time(22, 30),
        )

        evaluation = trace_rule_evaluation(rule, state, context, None)

        assert evaluation.result == RuleResult.SKIPPED
        assert evaluation.when_clause.satisfied
        assert "occupancy == away" in evaluation.failed_conditions

    def test_trace_suppressed_rule(self) -> None:
        """Trace a rule that matched but was suppressed."""
        rule = PolicyRule(
            rule_id="laundry-done",
            when=PolicyCondition(domain="laundry", state="done"),
            suppress_if={"sleep": "asleep"},
            classify=PolicyClassification(importance="low"),
        )
        state = DomainState(domain="laundry", state="done")
        context = EvaluationContext(
            domain_states={
                "laundry": state,
                "sleep": DomainState(domain="sleep", state="asleep"),
            },
            current_time=time(3, 15),
        )
        intent = IntentCandidate(
            domain="laundry",
            rule_id="laundry-done",
            importance=Importance.LOW,
            suppressed=True,
            suppression_reason="sleep=asleep",
        )

        evaluation = trace_rule_evaluation(rule, state, context, intent)

        assert evaluation.result == RuleResult.SUPPRESSED
        assert evaluation.when_clause.satisfied
        assert len(evaluation.suppress_if_checks) == 1
        assert evaluation.suppress_if_checks[0].satisfied
        assert evaluation.suppress_reason == "sleep=asleep"


# --- Test helpers ---


def _create_minimal_trace():
    """Create a minimal trace for testing."""
    from trestle_coordinator_core.trace import DecisionTrace

    return DecisionTrace(
        trace_id="test-trace",
        timestamp=datetime.now(),
        profile_id="test-profile",
        trigger=Trigger(type=TriggerType.STATE_CHANGE, domain="test"),
        domain_snapshot=DomainSnapshot(domains=[], snapshot_time=datetime.now()),
        policy_trace=PolicyEvaluationTrace(rules=[]),
        outcome=DecisionOutcome(type=OutcomeType.NO_ACTION),
    )


def PolicyEvaluationTrace(
    rules=None,
    quiet_hours=None,
    rules_evaluated=0,
    rules_matched=0,
    rules_skipped=0,
):
    """Helper to create PolicyEvaluationTrace."""
    from trestle_coordinator_core.trace import (
        PolicyEvaluationTrace as PET,
    )

    return PET(
        rules=rules or [],
        quiet_hours=quiet_hours,
        rules_evaluated=rules_evaluated,
        rules_matched=rules_matched,
        rules_skipped=rules_skipped,
    )
