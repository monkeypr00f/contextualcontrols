"""Adaptive learning stays deterministic and bounded."""

from datetime import UTC, datetime, timedelta

from custom_components.contextual_controls.adaptive import (
    AdaptiveSettings,
    LearningEngine,
    context_fingerprint,
)
from custom_components.contextual_controls.models import Ranked, Usage

START = datetime(2026, 9, 1, 20, tzinfo=UTC)
SETTINGS = AdaptiveSettings(
    minimum_transition_occurrences=3,
    source_weights={"manual": 1.0},
)


def action(entity: str, moment: datetime, user: str | None = "alice") -> Usage:
    return Usage(moment, entity, user, "manual", "turn_on", 1.0, presence_home=True)


def train(engine: LearningEngine, count: int = 3, delay_minutes: int = 5) -> datetime:
    moment = START
    for _index in range(count):
        engine.record_action(action("media_player.tv", moment), SETTINGS)
        moment += timedelta(minutes=delay_minutes)
        engine.record_action(action("script.goodnight", moment), SETTINGS)
        moment += timedelta(minutes=1)
    engine.record_action(action("media_player.tv", moment), SETTINGS)
    return moment


def train_chain(engine: LearningEngine, count: int = 3) -> datetime:
    moment = START
    for _index in range(count):
        engine.record_action(action("media_player.tv", moment), SETTINGS)
        moment += timedelta(minutes=2)
        engine.record_action(action("light.living_room", moment), SETTINGS)
        moment += timedelta(minutes=3)
        engine.record_action(action("script.goodnight", moment), SETTINGS)
        moment += timedelta(minutes=1)
    engine.record_action(action("media_player.tv", moment), SETTINGS)
    moment += timedelta(minutes=2)
    engine.record_action(action("light.living_room", moment), SETTINGS)
    return moment


def test_a_to_b_transition_and_minimum_occurrences():
    engine = LearningEngine()
    moment = train(engine, 2)
    assert engine.get_sequence_score("script.goodnight", moment, SETTINGS).score == 0
    engine = LearningEngine()
    moment = train(engine, 3)
    signal = engine.get_sequence_score("script.goodnight", moment + timedelta(minutes=4), SETTINGS)
    assert signal.score > 0
    assert signal.count == 3
    assert signal.predecessor == "media_player.tv"


def test_transition_outside_window_is_not_recorded():
    engine = LearningEngine()
    engine.record_action(action("cover.garage", START), SETTINGS)
    engine.record_action(action("light.entry", START + timedelta(minutes=31)), SETTINGS)
    assert not engine.transitions


def test_a_to_b_to_c_chain_requires_support_and_uses_two_recent_actions():
    engine = LearningEngine()
    moment = train_chain(engine, 2)
    assert engine.get_sequence_score("script.goodnight", moment, SETTINGS).depth == 0

    engine = LearningEngine()
    moment = train_chain(engine, 3)
    signal = engine.get_sequence_score(
        "script.goodnight", moment + timedelta(minutes=3), SETTINGS, user_id="alice"
    )
    assert signal.score > 0
    assert signal.depth == 2
    assert signal.predecessors == ("media_player.tv", "light.living_room")
    assert signal.count == 3
    ranked = engine.apply_adaptive(
        [Ranked("script.goodnight", 0.5, "habit")],
        moment + timedelta(minutes=3),
        SETTINGS,
        "alice",
        True,
    )[0]
    assert ranked.sequence_depth == 2
    assert ranked.reason_key == "sequence_chain_habit"


def test_chain_is_not_learned_when_one_step_is_outside_window():
    engine = LearningEngine()
    engine.record_action(action("cover.garage", START), SETTINGS)
    engine.record_action(action("light.entry", START + timedelta(minutes=31)), SETTINGS)
    engine.record_action(action("climate.living", START + timedelta(minutes=32)), SETTINGS)
    assert not engine.chains


def test_chain_persistence_cleanup_and_selective_reset():
    engine = LearningEngine()
    moment = train_chain(engine)
    restored = LearningEngine(engine.export())
    assert restored.top_chains("script.goodnight")[0]["entities"] == [
        "media_player.tv",
        "light.living_room",
    ]
    restored.reset_sequence(entity_id="light.living_room")
    assert not restored.chains

    restored = LearningEngine(engine.export())
    assert restored.cleanup(moment + timedelta(days=91), 90) > 0
    assert not restored.chains


def test_transition_decay_reduces_signal():
    engine = LearningEngine()
    moment = train(engine)
    recent = engine.get_sequence_score("script.goodnight", moment, SETTINGS).score
    # Recreate the recent trigger without teaching another transition.
    engine._latest_action = action("media_player.tv", moment + timedelta(days=60))
    old = engine.get_sequence_score(
        "script.goodnight", moment + timedelta(days=60, minutes=4), SETTINGS
    ).score
    assert recent > old


def test_sequence_boost_preserves_base_and_bounds_score():
    engine = LearningEngine()
    moment = train(engine)
    base = [Ranked("script.goodnight", 0.5, "habit")]
    adaptive = engine.apply_sequence(base, moment + timedelta(minutes=4), SETTINGS)
    assert adaptive[0].base_score == 0.5
    assert adaptive[0].sequence_score > 0
    assert 0.5 < adaptive[0].score <= 1


def test_sequence_persistence_round_trip_and_cleanup():
    engine = LearningEngine()
    moment = train(engine)
    restored = LearningEngine(engine.export())
    assert restored.top_predecessors("script.goodnight")[0]["count"] == 3
    assert restored.cleanup(moment + timedelta(days=91), 90) > 0
    assert not restored.transitions


def expose(
    engine: LearningEngine,
    entity: str,
    moment: datetime,
    settings: AdaptiveSettings,
    *,
    rank: int = 1,
    user: str | None = "alice",
) -> str:
    fingerprint = context_fingerprint(moment, True)
    engine.record_exposure(
        [{"entity_id": entity, "rank": rank, "score": 0.6}],
        moment,
        settings,
        context_hash=fingerprint,
        confidence=1,
        user_id=user,
        force=True,
    )
    return fingerprint


def test_ignored_suggestion_requires_minimum_exposures_and_is_smoothed():
    settings = AdaptiveSettings(minimum_exposures=5, acceptance_window_minutes=10)
    engine = LearningEngine()
    moment = START
    context = ""
    for _index in range(4):
        context = expose(engine, "climate.bedroom", moment, settings)
        moment += timedelta(minutes=11)
        engine.cleanup(moment, 90, settings)
    before = engine.feedback_signal("climate.bedroom", context, settings, user_id="alice")
    assert before.ignore_penalty == 0
    expose(engine, "climate.bedroom", moment, settings)
    moment += timedelta(minutes=11)
    engine.cleanup(moment, 90, settings)
    after = engine.feedback_signal("climate.bedroom", context, settings, user_id="alice")
    assert 0 < after.acceptance_rate < 0.5
    assert 0 < after.ignore_penalty < 1


def test_accepted_suggestion_and_acceptance_boost():
    settings = AdaptiveSettings(minimum_exposures=3, acceptance_window_minutes=10)
    engine = LearningEngine()
    moment = START
    context = ""
    for _index in range(5):
        context = expose(engine, "cover.bedroom", moment, settings)
        used = action("cover.bedroom", moment + timedelta(minutes=2))
        assert engine.resolve_exposure(used, settings, now=used.timestamp) == 1
        moment += timedelta(minutes=12)
    signal = engine.feedback_signal("cover.bedroom", context, settings, user_id="alice")
    assert signal.acceptance_rate > 0.5
    assert signal.acceptance_score > 0
    assert signal.ignore_penalty == 0
    base = [Ranked("cover.bedroom", 0.5, "habit")]
    assert engine.apply_adaptive(base, moment, settings, "alice", True, context)[0].score > 0.5


def test_rank_visibility_weights_ignored_feedback():
    settings = AdaptiveSettings(minimum_exposures=3, acceptance_window_minutes=2)
    engine = LearningEngine()
    moment = START
    for _index in range(5):
        context = expose(engine, "light.first", moment, settings, rank=1)
        expose(engine, "light.sixth", moment, settings, rank=6)
        moment += timedelta(minutes=3)
        engine.cleanup(moment, 90, settings)
    first = engine.feedback_signal("light.first", context, settings, user_id="alice")
    sixth = engine.feedback_signal("light.sixth", context, settings, user_id="alice")
    assert first.ignore_penalty > sixth.ignore_penalty


def test_acceptance_recovery_reduces_ignore_penalty():
    settings = AdaptiveSettings(minimum_exposures=3, acceptance_window_minutes=2)
    engine = LearningEngine()
    moment = START
    context = ""
    for _index in range(6):
        context = expose(engine, "light.recover", moment, settings)
        moment += timedelta(minutes=3)
        engine.cleanup(moment, 90, settings)
    initial = engine.feedback_signal("light.recover", context, settings, user_id="alice")
    for _index in range(10):
        expose(engine, "light.recover", moment, settings)
        used = action("light.recover", moment + timedelta(seconds=30))
        engine.resolve_exposure(used, settings, now=used.timestamp)
        moment += timedelta(minutes=3)
    recovered = engine.feedback_signal("light.recover", context, settings, user_id="alice")
    assert recovered.ignore_penalty < initial.ignore_penalty
    assert recovered.acceptance_rate > initial.acceptance_rate


def test_predictive_score_is_bounded_and_zero_influence_preserves_base():
    assert (
        LearningEngine.get_predictive_score(0.6, 1, 1, 0, AdaptiveSettings(prediction_influence=0))
        == 0.6
    )
    boosted = LearningEngine.get_predictive_score(0.6, 1, 1, 0, AdaptiveSettings())
    penalized = LearningEngine.get_predictive_score(0.6, 0, 0, 1, AdaptiveSettings())
    assert 0.6 < boosted <= 1
    assert 0 <= penalized < 0.6
    zero_base = LearningEngine.get_predictive_score(0, 1, 0, 0, AdaptiveSettings())
    assert 0 < zero_base <= 1


def test_top1_top3_and_offline_comparison_metrics():
    settings = AdaptiveSettings(acceptance_window_minutes=10)
    engine = LearningEngine()
    context = context_fingerprint(START, True)
    rows = [
        {"entity_id": "light.first", "rank": 1, "score": 0.8},
        {"entity_id": "script.third", "rank": 3, "score": 0.6},
    ]
    engine.record_exposure(
        rows,
        START,
        settings,
        context_hash=context,
        confidence=1,
        base_ranks={"light.first": 4, "script.third": 1},
        adaptive_ranks={"light.first": 1, "script.third": 3},
        force=True,
    )
    engine.resolve_exposure(action("light.first", START + timedelta(minutes=1)), settings)
    metrics = engine.metrics_snapshot()
    assert metrics["top1_hit_rate"] == 1
    assert metrics["top3_hit_rate"] == 1
    assert metrics["base_top3_hit_rate"] == 0
    assert metrics["adaptive_top3_hit_rate"] == 1


def test_top3_hit_and_metrics_survive_restart():
    settings = AdaptiveSettings(acceptance_window_minutes=10)
    engine = LearningEngine()
    context = context_fingerprint(START, True)
    engine.record_exposure(
        [
            {"entity_id": "light.first", "rank": 1, "score": 0.8},
            {"entity_id": "script.third", "rank": 3, "score": 0.6},
        ],
        START,
        settings,
        context_hash=context,
        confidence=1,
        force=True,
    )
    engine.resolve_exposure(action("script.third", START + timedelta(minutes=1)), settings)
    restored = LearningEngine(engine.export())
    metrics = restored.metrics_snapshot()
    assert metrics["top1_hit_rate"] == 0
    assert metrics["top3_hit_rate"] == 1
    assert metrics["accepted_suggestions"] == 1


def test_per_user_scope_and_hybrid_global_fallback():
    engine = LearningEngine()
    moment = train(engine, 3)
    bob_trigger = action("media_player.tv", moment + timedelta(minutes=1), user="bob")
    engine.record_action(bob_trigger, SETTINGS)
    per_user = AdaptiveSettings(
        learning_scope="user",
        minimum_transition_occurrences=3,
        source_weights={"manual": 1.0},
    )
    hybrid = AdaptiveSettings(
        learning_scope="hybrid",
        minimum_transition_occurrences=3,
        source_weights={"manual": 1.0},
    )
    query_time = bob_trigger.timestamp + timedelta(minutes=4)
    assert (
        engine.get_sequence_score("script.goodnight", query_time, per_user, user_id="bob").score
        == 0
    )
    assert (
        engine.get_sequence_score("script.goodnight", query_time, hybrid, user_id="bob").score > 0
    )


def test_zero_weight_source_does_not_teach_transition():
    engine = LearningEngine()
    settings = AdaptiveSettings(source_weights={"automation": 0})
    first = Usage(START, "light.a", None, "automation", "turn_on", 1)
    second = Usage(START + timedelta(minutes=1), "light.b", None, "automation", "turn_on", 1)
    engine.record_action(first, settings)
    engine.record_action(second, settings)
    assert not engine.transitions


def test_exposure_retention_cleanup():
    engine = LearningEngine()
    settings = AdaptiveSettings(acceptance_window_minutes=2)
    expose(engine, "light.old", START, settings)
    engine.cleanup(START + timedelta(days=31), 30, settings)
    assert not engine.exposures


def test_selective_sequence_and_feedback_reset():
    engine = LearningEngine()
    moment = train(engine, 3)
    settings = AdaptiveSettings(minimum_exposures=1, acceptance_window_minutes=10)
    expose(engine, "script.goodnight", moment, settings)
    engine.resolve_exposure(action("script.goodnight", moment + timedelta(minutes=1)), settings)

    assert engine.transitions
    assert engine.feedback
    engine.reset_sequence(entity_id="script.goodnight")
    assert not any(stat.to_entity == "script.goodnight" for stat in engine.transitions.values())
    assert engine.feedback

    engine.reset_feedback(entity_id="script.goodnight")
    assert not engine.feedback
    assert not engine.exposures
