"""Deterministic, explainable statistical ranking without Home Assistant."""

import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta

from .eligibility import available
from .models import Candidate, Ranked, ScoringSettings, Usage


def clock_distance(first: datetime, second: datetime) -> float:
    """Circular local wall-clock distance, in minutes, including midnight."""
    a = first.hour * 60 + first.minute + first.second / 60
    b = second.hour * 60 + second.minute + second.second / 60
    difference = abs(a - b)
    return min(difference, 1440 - difference)


def time_similarity(first: datetime, second: datetime, window: int) -> float:
    return 0.05 + 0.95 * max(0.0, 1 - clock_distance(first, second) / window)


def recency_decay(age_days: float, weight: float) -> float:
    if weight <= 0:
        return 1.0
    return math.exp(-max(0.0, age_days) / (90 - 87 * min(weight, 100) / 100))


def state_weight(action: str, state: str) -> float:
    """Penalize satisfied simple actions; never infer scene semantics."""
    satisfied = {
        "turn_on": "on",
        "turn_off": "off",
        "open_cover": "open",
        "close_cover": "closed",
        "lock": "locked",
        "unlock": "unlocked",
    }
    return 0.5 if satisfied.get(action) == state else 1.0


def rank(
    candidates: Iterable[Candidate],
    records: Iterable[Usage],
    now: datetime,
    settings: ScoringSettings,
) -> list[Ranked]:
    """Pure snapshot evaluation; now must use HA's configured timezone."""
    grouped: dict[str, list[Usage]] = defaultdict(list)
    minimum = now - timedelta(days=settings.learning_period_days)
    for record in records:
        if (
            minimum <= record.timestamp <= now
            and record.entity_id not in settings.ignored_entities
            and record.source in settings.learn_sources
            and (not settings.user_id or record.user_id == settings.user_id)
        ):
            grouped[record.entity_id].append(record)
    result = []
    for candidate in candidates:
        if not available(candidate) or candidate.entity_id in settings.ignored_entities:
            continue
        events = grouped[candidate.entity_id]
        count = len(events)
        if count < 3 and settings.cold_start == "pinned":
            continue
        evidence = times = recencies = confidences = states = 0.0
        in_window = 0
        for event in events:
            local_time = event.timestamp.astimezone(now.tzinfo)
            age = (now.timestamp() - event.timestamp.timestamp()) / 86400
            time = time_similarity(local_time, now, settings.time_window_minutes)
            recency = recency_decay(age, settings.recency_weight)
            state = state_weight(event.action, candidate.state)
            evidence += time * recency * event.confidence * state
            times += time
            recencies += recency
            confidences += event.confidence
            states += state
            in_window += clock_distance(local_time, now) <= settings.time_window_minutes
        score = 1 - math.exp(-evidence / 3)
        reason = "habit"
        if count < 3 and events:
            if settings.cold_start == "recent":
                latest = max(events, key=lambda event: event.timestamp)
                age = (now.timestamp() - latest.timestamp.timestamp()) / 86400
                score = max(score, 0.45 * latest.confidence * math.exp(-age / 3))
                reason = "recent"
            elif settings.cold_start == "frequent":
                score = max(score, 1 - math.exp(-confidences / 3))
                reason = "frequent"
        if not events and settings.cold_start == "domains":
            score = 0.2
            reason = "domain_default"
        if score < settings.minimum_confidence / 100 or score <= 0:
            continue
        result.append(
            Ranked(
                candidate.entity_id,
                round(score, 4),
                reason,
                in_window,
                frequency=count / settings.learning_period_days,
                time=times / max(1, count),
                recency=recencies / max(1, count),
                confidence=confidences / max(1, count),
                current_state=states / max(1, count),
            )
        )
    return sorted(result, key=lambda item: (-item.score, item.entity_id))
