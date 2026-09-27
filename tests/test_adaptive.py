"""Adaptive learning stays deterministic and bounded."""

from datetime import UTC, datetime, timedelta

from custom_components.contextual_controls.adaptive import AdaptiveSettings, LearningEngine
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
