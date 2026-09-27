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
