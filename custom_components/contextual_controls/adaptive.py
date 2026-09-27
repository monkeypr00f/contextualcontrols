"""Local, deterministic adaptive learning aggregates.

This module has no Home Assistant imports so its behavior is easy to test.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from .models import Ranked, Usage

GLOBAL_PROFILE = "__global__"
UNKNOWN_ACTOR = "__unknown__"
MAX_DELAY_SAMPLES = 64


def time_bucket(moment: datetime) -> str:
    hour = moment.hour
    if 6 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def day_bucket(moment: datetime) -> str:
    return "weekend" if moment.weekday() >= 5 else "weekday"


def presence_bucket(value: bool | None) -> str:
    return "home" if value is True else "away" if value is False else "unknown"


@dataclass(frozen=True, slots=True)
class AdaptiveSettings:
    enabled: bool = True
    sequence_enabled: bool = True
    sequence_window_minutes: int = 30
    sequence_influence: float = 30
    minimum_transition_occurrences: int = 3
    sequence_decay_days: int = 30
    prediction_influence: float = 35
    learning_scope: str = "hybrid"
    retention_days: int = 90
    source_weights: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class TransitionStat:
    profile: str
    from_entity: str
    to_entity: str
    count: int = 0
    weighted_count: float = 0.0
    delay_sum: float = 0.0
    delays: list[float] = field(default_factory=list)
    last_seen: datetime | None = None
    time_buckets: dict[str, float] = field(default_factory=dict)
    day_buckets: dict[str, float] = field(default_factory=dict)
    presence_buckets: dict[str, float] = field(default_factory=dict)

    @property
    def average_delay_seconds(self) -> float:
        return self.delay_sum / self.weighted_count if self.weighted_count else 0.0

    @property
    def median_delay_seconds(self) -> float:
        return float(median(self.delays)) if self.delays else 0.0

    def observe(self, delay: float, weight: float, moment: datetime, presence: bool | None) -> None:
        self.count += 1
        self.weighted_count += weight
        self.delay_sum += delay * weight
        self.delays.append(delay)
        if len(self.delays) > MAX_DELAY_SAMPLES:
            del self.delays[: len(self.delays) - MAX_DELAY_SAMPLES]
        self.last_seen = moment
        for mapping, key in (
            (self.time_buckets, time_bucket(moment)),
            (self.day_buckets, day_bucket(moment)),
            (self.presence_buckets, presence_bucket(presence)),
        ):
            mapping[key] = mapping.get(key, 0.0) + weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "from": self.from_entity,
            "to": self.to_entity,
            "count": self.count,
            "weighted_count": self.weighted_count,
            "delay_sum": self.delay_sum,
            "delays": list(self.delays),
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "time_buckets": dict(self.time_buckets),
            "day_buckets": dict(self.day_buckets),
            "presence_buckets": dict(self.presence_buckets),
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> TransitionStat:
        last_seen = datetime.fromisoformat(row["last_seen"]) if row.get("last_seen") else None
        return cls(
            profile=str(row["profile"]),
            from_entity=str(row["from"]),
            to_entity=str(row["to"]),
            count=max(0, int(row.get("count", 0))),
            weighted_count=max(0.0, float(row.get("weighted_count", 0))),
            delay_sum=max(0.0, float(row.get("delay_sum", 0))),
            delays=[max(0.0, float(value)) for value in row.get("delays", [])][-MAX_DELAY_SAMPLES:],
            last_seen=last_seen,
            time_buckets={
                str(k): max(0.0, float(v)) for k, v in row.get("time_buckets", {}).items()
            },
            day_buckets={str(k): max(0.0, float(v)) for k, v in row.get("day_buckets", {}).items()},
            presence_buckets={
                str(k): max(0.0, float(v)) for k, v in row.get("presence_buckets", {}).items()
            },
        )


@dataclass(frozen=True, slots=True)
class SequenceSignal:
    score: float = 0.0
    confidence: float = 0.0
    count: int = 0
    predecessor: str | None = None
    average_delay_seconds: float = 0.0
    median_delay_seconds: float = 0.0


class LearningEngine:
    """Incremental transition model with bounded ephemeral action buffers."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.transitions: dict[tuple[str, str, str], TransitionStat] = {}
        self._recent_by_actor: dict[str, deque[Usage]] = defaultdict(lambda: deque(maxlen=5))
        self._latest_action: Usage | None = None
        self.rejected = 0
        if data:
            self.load(data)

    def load(self, data: dict[str, Any]) -> None:
        rows = data.get("transitions", [])
        if not isinstance(rows, list):
            self.rejected += 1
            return
        for row in rows:
            try:
                stat = TransitionStat.from_dict(row)
                if not stat.from_entity or not stat.to_entity or stat.last_seen is None:
                    raise ValueError
                self.transitions[(stat.profile, stat.from_entity, stat.to_entity)] = stat
            except KeyError, TypeError, ValueError, OverflowError:
                self.rejected += 1

    def export(self) -> dict[str, Any]:
        return {
            "transitions": [
                stat.to_dict()
                for _key, stat in sorted(self.transitions.items(), key=lambda item: item[0])
            ]
        }

    @staticmethod
    def _weight(record: Usage, settings: AdaptiveSettings) -> float:
        detail = record.source_detail or record.source
        configured = settings.source_weights.get(
            detail, settings.source_weights.get(record.source, 1.0)
        )
        return max(0.0, min(1.0, float(configured))) * record.confidence

    def record_action(
        self,
        record: Usage,
        settings: AdaptiveSettings,
        *,
        local_timestamp: datetime | None = None,
    ) -> None:
        if not settings.enabled or not settings.sequence_enabled:
            return
        weight = self._weight(record, settings)
        if weight <= 0:
            return
        actor = record.user_id or UNKNOWN_ACTOR
        recent = self._recent_by_actor[actor]
        previous = recent[-1] if recent else None
        moment = local_timestamp or record.timestamp
        if previous is not None and previous.entity_id != record.entity_id:
            delay = (record.timestamp - previous.timestamp).total_seconds()
            if 0 < delay <= settings.sequence_window_minutes * 60:
                profiles = [GLOBAL_PROFILE]
                if record.user_id:
                    profiles.append(record.user_id)
                for profile in profiles:
                    key = (profile, previous.entity_id, record.entity_id)
                    stat = self.transitions.get(key)
                    if stat is None:
                        stat = self.transitions[key] = TransitionStat(
                            profile, previous.entity_id, record.entity_id
                        )
                    stat.observe(delay, weight, moment, record.presence_home)
        recent.append(record)
        self._latest_action = record

    @staticmethod
    def _distribution_similarity(mapping: dict[str, float], key: str) -> float:
        total = sum(mapping.values())
        if total <= 0:
            return 1.0
        return 0.65 + 0.35 * mapping.get(key, 0.0) / total

    def _select_stat(
        self,
        from_entity: str,
        to_entity: str,
        user_id: str | None,
        settings: AdaptiveSettings,
    ) -> TransitionStat | None:
        global_stat = self.transitions.get((GLOBAL_PROFILE, from_entity, to_entity))
        user_stat = self.transitions.get((user_id, from_entity, to_entity)) if user_id else None
        if settings.learning_scope == "user":
            return user_stat
        if settings.learning_scope == "global":
            return global_stat
        if user_stat and user_stat.count >= settings.minimum_transition_occurrences:
            return user_stat
        return global_stat

    def get_sequence_score(
        self,
        entity_id: str,
        now: datetime,
        settings: AdaptiveSettings,
        *,
        user_id: str | None = None,
        presence_home: bool | None = None,
    ) -> SequenceSignal:
        if not settings.enabled or not settings.sequence_enabled:
            return SequenceSignal()
        previous: Usage | None
        if user_id and self._recent_by_actor.get(user_id):
            previous = self._recent_by_actor[user_id][-1]
        else:
            previous = self._latest_action
        if previous is None or previous.entity_id == entity_id:
            return SequenceSignal()
        delay = now.timestamp() - previous.timestamp.timestamp()
        if delay < 0 or delay > settings.sequence_window_minutes * 60:
            return SequenceSignal()
        stat = self._select_stat(previous.entity_id, entity_id, user_id, settings)
        if (
            stat is None
            or stat.count < settings.minimum_transition_occurrences
            or not stat.last_seen
        ):
            return SequenceSignal()
        support = 1 - math.exp(-(stat.count - settings.minimum_transition_occurrences + 1) / 3)
        age_days = max(0.0, (now.timestamp() - stat.last_seen.timestamp()) / 86400)
        recency = math.exp(-age_days / max(1, settings.sequence_decay_days))
        learned_delay = stat.average_delay_seconds
        delay_match = math.exp(
            -abs(delay - learned_delay) / max(60, settings.sequence_window_minutes * 60)
        )
        context = (
            self._distribution_similarity(stat.time_buckets, time_bucket(now))
            * self._distribution_similarity(stat.day_buckets, day_bucket(now))
            * self._distribution_similarity(stat.presence_buckets, presence_bucket(presence_home))
        ) ** (1 / 3)
        evidence_quality = min(1.0, stat.weighted_count / max(1, stat.count))
        confidence = max(0.0, min(1.0, support * recency * context * evidence_quality))
        score = max(0.0, min(1.0, confidence * delay_match))
        return SequenceSignal(
            score=round(score, 4),
            confidence=round(confidence, 4),
            count=stat.count,
            predecessor=previous.entity_id,
            average_delay_seconds=round(learned_delay, 1),
            median_delay_seconds=round(stat.median_delay_seconds, 1),
        )

    def cleanup(self, now: datetime, retention_days: int) -> int:
        cutoff = now - timedelta(days=retention_days)
        stale = [
            key
            for key, stat in self.transitions.items()
            if stat.last_seen is None or stat.last_seen < cutoff
        ]
        for key in stale:
            del self.transitions[key]
        return len(stale)

    def reset_sequence(self, *, entity_id: str | None = None, user_id: str | None = None) -> None:
        self.transitions = {
            key: stat
            for key, stat in self.transitions.items()
            if not (
                (entity_id is None or entity_id in (stat.from_entity, stat.to_entity))
                and (user_id is None or stat.profile == user_id)
            )
        }
        if entity_id is None and user_id is None:
            self._recent_by_actor.clear()
            self._latest_action = None

    def top_predecessors(
        self, entity_id: str, *, user_id: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        profile = user_id or GLOBAL_PROFILE
        matches = [
            stat
            for stat in self.transitions.values()
            if stat.profile == profile and stat.to_entity == entity_id
        ]
        matches.sort(key=lambda stat: (-stat.count, stat.from_entity))
        return [
            {
                "entity_id": stat.from_entity,
                "count": stat.count,
                "confidence": round(1 - math.exp(-stat.count / 3), 4),
                "average_delay_seconds": round(stat.average_delay_seconds, 1),
                "median_delay_seconds": round(stat.median_delay_seconds, 1),
            }
            for stat in matches[:limit]
        ]

    def counts(self) -> dict[str, Any]:
        supported = sum(1 for stat in self.transitions.values() if stat.count >= 3)
        return {
            "sequence_patterns": len(self.transitions),
            "supported_sequence_patterns": supported,
            "adaptive_rejected_records": self.rejected,
        }

    def apply_sequence(
        self,
        ranked: list[Ranked],
        now: datetime,
        settings: AdaptiveSettings,
        user_id: str | None = None,
        presence_home: bool | None = None,
    ) -> list[Ranked]:
        """Add a bounded sequence signal after the unchanged base scorer."""
        if not settings.enabled or not settings.sequence_enabled:
            return [replace(item, base_score=item.score) for item in ranked]
        prediction_weight = max(0.0, min(1.0, settings.prediction_influence / 100))
        sequence_weight = max(0.0, min(1.0, settings.sequence_influence / 100))
        result: list[Ranked] = []
        for item in ranked:
            signal = self.get_sequence_score(
                item.entity_id,
                now,
                settings,
                user_id=user_id,
                presence_home=presence_home,
            )
            target = item.score + sequence_weight * signal.score * (1 - item.score)
            final = item.score + prediction_weight * (min(1.0, target) - item.score)
            reason = "sequence_habit" if signal.score > 0.25 else item.reason_key
            result.append(
                replace(
                    item,
                    score=round(max(0.0, min(1.0, final)), 4),
                    reason_key=reason,
                    source="adaptive" if signal.score else item.source,
                    base_score=item.score,
                    sequence_score=signal.score,
                    adaptive_confidence=signal.confidence,
                )
            )
        return sorted(result, key=lambda item: (-item.score, item.entity_id))
