"""Behavioral statistical tests: clock boundaries, evidence and plausibility."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.contextual_controls.models import Candidate, ScoringSettings, Usage
from custom_components.contextual_controls.scoring import (
    clock_distance,
    rank,
    recency_decay,
    state_weight,
    time_similarity,
)

NOW = datetime(2026, 9, 24, 23, 30, tzinfo=ZoneInfo("Europe/Rome"))
SETTINGS = ScoringSettings(minimum_confidence=0)


def use(entity="light.bed", days=1, hour=23, user="alice", **kwargs):
    return Usage(
        (NOW - timedelta(days=days)).replace(hour=hour),
        entity,
        user,
        kwargs.get("source", "user"),
        kwargs.get("action", "turn_off"),
        kwargs.get("confidence", 0.9),
    )


@pytest.mark.parametrize(("a", "b", "expected"), [(23, 0, 60), (1, 23, 120), (12, 0, 720)])
def test_midnight(a, b, expected):
    assert clock_distance(NOW.replace(hour=a), NOW.replace(hour=b)) == expected


def test_window_changes_evidence():
    other = NOW - timedelta(minutes=60)
    assert time_similarity(other, NOW, 30) < time_similarity(other, NOW, 90)
    assert time_similarity(NOW, NOW, 90) == 1


def test_recency():
    assert recency_decay(2, 70) > recency_decay(20, 70)
    assert recency_decay(20, 100) < recency_decay(20, 70)
    assert recency_decay(90, 0) == 1


def test_evening_beats_morning_then_reverses():
    candidates = [Candidate("light.bed", "on"), Candidate("light.kitchen", "on")]
    records = [use(days=n) for n in range(1, 8)] + [
        use("light.kitchen", days=n, hour=8) for n in range(1, 8)
    ]
    assert rank(candidates, records, NOW, SETTINGS)[0].entity_id == "light.bed"
    assert rank(candidates, records, NOW.replace(hour=8), SETTINGS)[0].entity_id == "light.kitchen"


def test_repetition_changes_ranking():
    candidates = [Candidate("light.bed", "on"), Candidate("light.kitchen", "on")]
    records = [use("light.kitchen", days=n) for n in range(1, 4)] + [use()]
    assert rank(candidates, records, NOW, SETTINGS)[0].entity_id == "light.kitchen"
    records += [use(days=n) for n in range(2, 9)]
    assert rank(candidates, records, NOW, SETTINGS)[0].entity_id == "light.bed"


def test_current_state_keeps_useful_off_command():
    records = [use(days=n) for n in range(1, 10)]
    on = rank([Candidate("light.bed", "on")], records, NOW, SETTINGS)[0]
    off = rank([Candidate("light.bed", "off")], records, NOW, SETTINGS)[0]
    assert on.score > off.score
    assert state_weight("turn_on", "unknown") == 1


def test_profile_filter_does_not_mix_users_or_unknown():
    settings = replace(SETTINGS, user_id="bob")
    assert not rank([Candidate("light.bed", "on")], [use(), use(user=None)], NOW, settings)
    assert rank([Candidate("light.bed", "on")], [use(user="bob")], NOW, settings)


def test_unknown_and_child_sources_opt_in():
    candidate = [Candidate("light.bed", "on")]
    records = [use(source="unknown", confidence=0.2) for _ in range(10)]
    assert not rank(candidate, records, NOW, SETTINGS)
    assert rank(candidate, records, NOW, replace(SETTINGS, learn_sources=("unknown",)))


def test_ignore_does_not_delete_history():
    rows = [use()]
    assert not rank(
        [Candidate("light.bed", "on")],
        rows,
        NOW,
        replace(SETTINGS, ignored_entities=("light.bed",)),
    )
    assert len(rows) == 1


def test_period_and_future_events_excluded():
    assert not rank([Candidate("light.bed", "on")], [use(days=22), use(days=-1)], NOW, SETTINGS)


def test_timezone_normalization():
    candidate = [Candidate("light.bed", "on")]
    records = [use(days=n) for n in range(1, 5)]
    converted = [replace(row, timestamp=row.timestamp.astimezone(UTC)) for row in records]
    assert rank(candidate, records, NOW, SETTINGS) == rank(candidate, converted, NOW, SETTINGS)


@pytest.mark.parametrize("strategy", ["recent", "frequent", "pinned"])
def test_cold_start_never_invents_evidence(strategy):
    assert not rank([Candidate("light.bed", "on")], [], NOW, replace(SETTINGS, cold_start=strategy))


def test_recent_default_bootstraps_one_command_but_pins_only_does_not():
    candidate = [Candidate("light.bed", "on")]
    assert rank(candidate, [use(days=0)], NOW, ScoringSettings())
    assert not rank(candidate, [use(days=0)], NOW, replace(SETTINGS, cold_start="pinned"))


def test_domain_defaults_require_explicit_strategy_and_threshold():
    candidates = [Candidate("light.bed", "on")]
    assert rank(candidates, [], NOW, replace(SETTINGS, cold_start="domains"))
    assert not rank(
        candidates, [], NOW, replace(SETTINGS, cold_start="domains", minimum_confidence=21)
    )


def test_confidence_and_threshold():
    candidate = [Candidate("light.bed", "on")]
    strong = rank(candidate, [use(days=n) for n in range(1, 6)], NOW, SETTINGS)[0]
    weak = rank(candidate, [use(days=n, confidence=0.2) for n in range(1, 6)], NOW, SETTINGS)[0]
    assert strong.score > weak.score
    assert not rank(candidate, [use()], NOW, replace(SETTINGS, minimum_confidence=100))


def test_stable_tie_and_bounded_scores():
    candidates = [Candidate("light.z", "on"), Candidate("light.a", "on")]
    rows = [use(c.entity_id, days=1) for c in candidates for _ in range(100)]
    result = rank(candidates, rows, NOW, SETTINGS)
    assert [item.entity_id for item in result] == ["light.a", "light.z"]
    assert all(0 <= item.score <= 1 for item in result)
