"""Local, deterministic adaptive learning aggregates.

This module has no Home Assistant imports so its behavior is easy to test.
"""

from __future__ import annotations

import hashlib
import json
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
    ignored_suggestion_learning: bool = True
    acceptance_window_minutes: int = 10
    minimum_exposures: int = 5
    ignored_penalty_strength: float = 25
    acceptance_boost: float = 15
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


@dataclass(slots=True)
class ChainStat:
    """Compact evidence for one bounded A→B→C pattern."""

    profile: str
    first_entity: str
    second_entity: str
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
            "first": self.first_entity,
            "second": self.second_entity,
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
    def from_dict(cls, row: dict[str, Any]) -> ChainStat:
        last_seen = datetime.fromisoformat(row["last_seen"]) if row.get("last_seen") else None
        return cls(
            profile=str(row["profile"]),
            first_entity=str(row["first"]),
            second_entity=str(row["second"]),
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
    predecessors: tuple[str, ...] = ()
    depth: int = 0
    average_delay_seconds: float = 0.0
    median_delay_seconds: float = 0.0


@dataclass(slots=True)
class Exposure:
    timestamp: datetime
    entity_id: str
    rank: int
    base_rank: int
    adaptive_rank: int
    score: float
    context_hash: str
    slot: int
    generation_id: int
    source: str = "unknown"
    confidence: float = 0.35
    user_id: str | None = None
    used: bool = False
    used_after_seconds: float | None = None
    resolved: bool = False
    metric_counted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "entity_id": self.entity_id,
            "rank": self.rank,
            "base_rank": self.base_rank,
            "adaptive_rank": self.adaptive_rank,
            "score": self.score,
            "context_hash": self.context_hash,
            "slot": self.slot,
            "generation_id": self.generation_id,
            "source": self.source,
            "confidence": self.confidence,
            "user_id": self.user_id,
            "used": self.used,
            "used_after_seconds": self.used_after_seconds,
            "resolved": self.resolved,
            "metric_counted": self.metric_counted,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> Exposure:
        return cls(
            timestamp=datetime.fromisoformat(row["timestamp"]),
            entity_id=str(row["entity_id"]),
            rank=max(1, int(row["rank"])),
            base_rank=max(0, int(row.get("base_rank", 0))),
            adaptive_rank=max(0, int(row.get("adaptive_rank", 0))),
            score=max(0.0, min(1.0, float(row.get("score", 0)))),
            context_hash=str(row.get("context_hash", "*")),
            slot=max(1, int(row.get("slot", row["rank"]))),
            generation_id=max(0, int(row.get("generation_id", 0))),
            source=str(row.get("source", "unknown")),
            confidence=max(0.0, min(1.0, float(row.get("confidence", 0.35)))),
            user_id=row.get("user_id") if isinstance(row.get("user_id"), str) else None,
            used=bool(row.get("used", False)),
            used_after_seconds=(
                max(0.0, float(row["used_after_seconds"]))
                if row.get("used_after_seconds") is not None
                else None
            ),
            resolved=bool(row.get("resolved", False)),
            metric_counted=bool(row.get("metric_counted", False)),
        )


@dataclass(slots=True)
class FeedbackStat:
    profile: str
    entity_id: str
    context_hash: str
    exposures: int = 0
    accepted: int = 0
    ignored: int = 0
    exposure_weight: float = 0.0
    accepted_weight: float = 0.0
    ignored_weight: float = 0.0
    last_seen: datetime | None = None

    def observe(self, accepted: bool, weight: float, moment: datetime) -> None:
        self.exposures += 1
        self.exposure_weight += weight
        if accepted:
            self.accepted += 1
            self.accepted_weight += weight
        else:
            self.ignored += 1
            self.ignored_weight += weight
        self.last_seen = moment

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "entity_id": self.entity_id,
            "context_hash": self.context_hash,
            "exposures": self.exposures,
            "accepted": self.accepted,
            "ignored": self.ignored,
            "exposure_weight": self.exposure_weight,
            "accepted_weight": self.accepted_weight,
            "ignored_weight": self.ignored_weight,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> FeedbackStat:
        return cls(
            profile=str(row["profile"]),
            entity_id=str(row["entity_id"]),
            context_hash=str(row.get("context_hash", "*")),
            exposures=max(0, int(row.get("exposures", 0))),
            accepted=max(0, int(row.get("accepted", 0))),
            ignored=max(0, int(row.get("ignored", 0))),
            exposure_weight=max(0.0, float(row.get("exposure_weight", 0))),
            accepted_weight=max(0.0, float(row.get("accepted_weight", 0))),
            ignored_weight=max(0.0, float(row.get("ignored_weight", 0))),
            last_seen=(datetime.fromisoformat(row["last_seen"]) if row.get("last_seen") else None),
        )


@dataclass(frozen=True, slots=True)
class FeedbackSignal:
    acceptance_score: float = 0.0
    acceptance_rate: float = 0.5
    ignore_penalty: float = 0.0
    confidence: float = 0.0
    exposures: int = 0


def context_fingerprint(
    moment: datetime,
    presence_home: bool | None,
    context_states: tuple[tuple[str, str], ...] = (),
) -> str:
    """Hash only a compact segment and explicitly configured context states."""
    document = {
        "time": time_bucket(moment),
        "day": day_bucket(moment),
        "presence": presence_bucket(presence_home),
        "context": sorted(context_states),
    }
    return hashlib.sha256(
        json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()[:16]


def visibility_weight(rank: int) -> float:
    return max(0.35, 1.0 - 0.1 * max(0, rank - 1))


class LearningEngine:
    """Incremental transition model with bounded ephemeral action buffers."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.transitions: dict[tuple[str, str, str], TransitionStat] = {}
        self.chains: dict[tuple[str, str, str, str], ChainStat] = {}
        self._recent_by_actor: dict[str, deque[Usage]] = defaultdict(lambda: deque(maxlen=5))
        self._recent_global: deque[Usage] = deque(maxlen=5)
        self.exposures: list[Exposure] = []
        self.feedback: dict[tuple[str, str, str], FeedbackStat] = {}
        self.generation = 0
        self.metrics: dict[str, int] = {
            "total_suggestions": 0,
            "accepted_suggestions": 0,
            "ignored_suggestions": 0,
            "prediction_windows": 0,
            "top1_hits": 0,
            "top3_hits": 0,
            "base_top3_hits": 0,
            "adaptive_top3_hits": 0,
        }
        self.last_learning_update: datetime | None = None
        self._last_exposure_fingerprint: tuple[tuple[str, ...], str, str | None] | None = None
        self._last_exposure_at: datetime | None = None
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
        chain_rows = data.get("chains", [])
        if not isinstance(chain_rows, list):
            self.rejected += 1
            chain_rows = []
        for row in chain_rows:
            try:
                chain_stat = ChainStat.from_dict(row)
                if (
                    not chain_stat.first_entity
                    or not chain_stat.second_entity
                    or not chain_stat.to_entity
                    or chain_stat.last_seen is None
                ):
                    raise ValueError
                self.chains[
                    (
                        chain_stat.profile,
                        chain_stat.first_entity,
                        chain_stat.second_entity,
                        chain_stat.to_entity,
                    )
                ] = chain_stat
            except KeyError, TypeError, ValueError, OverflowError:
                self.rejected += 1
        exposure_rows = data.get("exposures", [])
        feedback_rows = data.get("feedback", [])
        if not isinstance(exposure_rows, list) or not isinstance(feedback_rows, list):
            self.rejected += 1
            return
        for row in exposure_rows:
            try:
                exposure = Exposure.from_dict(row)
                self.exposures.append(exposure)
                self.generation = max(self.generation, exposure.generation_id)
            except KeyError, TypeError, ValueError, OverflowError:
                self.rejected += 1
        for row in feedback_rows:
            try:
                feedback_stat = FeedbackStat.from_dict(row)
                self.feedback[
                    (feedback_stat.profile, feedback_stat.entity_id, feedback_stat.context_hash)
                ] = feedback_stat
            except KeyError, TypeError, ValueError, OverflowError:
                self.rejected += 1
        metrics = data.get("metrics", {})
        if isinstance(metrics, dict):
            for key in self.metrics:
                try:
                    self.metrics[key] = max(0, int(metrics.get(key, 0)))
                except TypeError, ValueError, OverflowError:
                    self.rejected += 1
            if metrics.get("last_learning_update"):
                try:
                    self.last_learning_update = datetime.fromisoformat(
                        metrics["last_learning_update"]
                    )
                except TypeError, ValueError:
                    self.rejected += 1

    def export(self) -> dict[str, Any]:
        return {
            "transitions": [
                stat.to_dict()
                for _key, stat in sorted(self.transitions.items(), key=lambda item: item[0])
            ],
            "chains": [
                stat.to_dict()
                for _key, stat in sorted(self.chains.items(), key=lambda item: item[0])
            ],
            "exposures": [row.to_dict() for row in self.exposures],
            "feedback": [
                stat.to_dict()
                for _key, stat in sorted(self.feedback.items(), key=lambda item: item[0])
            ],
            "metrics": {
                **self.metrics,
                "last_learning_update": self.last_learning_update.isoformat()
                if self.last_learning_update
                else None,
            },
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
        first = recent[-2] if len(recent) >= 2 else None
        moment = local_timestamp or record.timestamp
        profiles = [GLOBAL_PROFILE]
        if record.user_id:
            profiles.append(record.user_id)
        if previous is not None and previous.entity_id != record.entity_id:
            delay = (record.timestamp - previous.timestamp).total_seconds()
            if 0 < delay <= settings.sequence_window_minutes * 60:
                for profile in profiles:
                    key = (profile, previous.entity_id, record.entity_id)
                    stat = self.transitions.get(key)
                    if stat is None:
                        stat = self.transitions[key] = TransitionStat(
                            profile, previous.entity_id, record.entity_id
                        )
                    stat.observe(delay, weight, moment, record.presence_home)
        if (
            first is not None
            and previous is not None
            and first.entity_id != previous.entity_id
            and previous.entity_id != record.entity_id
        ):
            first_delay = (previous.timestamp - first.timestamp).total_seconds()
            second_delay = (record.timestamp - previous.timestamp).total_seconds()
            if (
                0 < first_delay <= settings.sequence_window_minutes * 60
                and 0 < second_delay <= settings.sequence_window_minutes * 60
            ):
                chain_weight = min(
                    self._weight(first, settings),
                    self._weight(previous, settings),
                    weight,
                )
                if chain_weight > 0:
                    for profile in profiles:
                        chain_key = (
                            profile,
                            first.entity_id,
                            previous.entity_id,
                            record.entity_id,
                        )
                        chain_stat = self.chains.get(chain_key)
                        if chain_stat is None:
                            chain_stat = self.chains[chain_key] = ChainStat(
                                profile,
                                first.entity_id,
                                previous.entity_id,
                                record.entity_id,
                            )
                        chain_stat.observe(second_delay, chain_weight, moment, record.presence_home)
        recent.append(record)
        self._recent_global.append(record)
        self.last_learning_update = record.timestamp

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

    def _select_chain(
        self,
        first_entity: str,
        second_entity: str,
        to_entity: str,
        user_id: str | None,
        settings: AdaptiveSettings,
    ) -> ChainStat | None:
        global_stat = self.chains.get((GLOBAL_PROFILE, first_entity, second_entity, to_entity))
        user_stat = (
            self.chains.get((user_id, first_entity, second_entity, to_entity)) if user_id else None
        )
        if settings.learning_scope == "user":
            return user_stat
        if settings.learning_scope == "global":
            return global_stat
        if user_stat and user_stat.count >= settings.minimum_transition_occurrences:
            return user_stat
        return global_stat

    def _sequence_signal(
        self,
        stat: TransitionStat | ChainStat | None,
        delay: float,
        now: datetime,
        settings: AdaptiveSettings,
        presence_home: bool | None,
        predecessors: tuple[str, ...],
    ) -> SequenceSignal:
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
            predecessor=predecessors[-1],
            predecessors=predecessors,
            depth=len(predecessors),
            average_delay_seconds=round(learned_delay, 1),
            median_delay_seconds=round(stat.median_delay_seconds, 1),
        )

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
        recent = self._recent_by_actor.get(user_id) if user_id else self._recent_global
        if not recent:
            return SequenceSignal()
        previous = recent[-1]
        if previous is None or previous.entity_id == entity_id:
            return SequenceSignal()
        delay = now.timestamp() - previous.timestamp.timestamp()
        if delay < 0 or delay > settings.sequence_window_minutes * 60:
            return SequenceSignal()
        pair = self._sequence_signal(
            self._select_stat(previous.entity_id, entity_id, user_id, settings),
            delay,
            now,
            settings,
            presence_home,
            (previous.entity_id,),
        )
        if len(recent) < 2:
            return pair
        first = recent[-2]
        first_delay = previous.timestamp.timestamp() - first.timestamp.timestamp()
        if (
            first.entity_id == previous.entity_id
            or first_delay <= 0
            or first_delay > settings.sequence_window_minutes * 60
        ):
            return pair
        chain = self._sequence_signal(
            self._select_chain(
                first.entity_id,
                previous.entity_id,
                entity_id,
                user_id,
                settings,
            ),
            delay,
            now,
            settings,
            presence_home,
            (first.entity_id, previous.entity_id),
        )
        return chain if chain.score >= pair.score and chain.depth == 2 else pair

    def record_exposure(
        self,
        rows: list[dict[str, Any]],
        now: datetime,
        settings: AdaptiveSettings,
        *,
        context_hash: str,
        source: str = "unknown",
        confidence: float = 0.35,
        user_id: str | None = None,
        base_ranks: dict[str, int] | None = None,
        adaptive_ranks: dict[str, int] | None = None,
        force: bool = False,
    ) -> int | None:
        """Persist a debounced ranking exposure without implying it was visible."""
        if not settings.enabled or not settings.ignored_suggestion_learning or not rows:
            return None
        entities = tuple(str(row["entity_id"]) for row in rows)
        fingerprint = (entities, context_hash, user_id)
        if (
            not force
            and fingerprint == self._last_exposure_fingerprint
            and self._last_exposure_at is not None
            and now - self._last_exposure_at < timedelta(minutes=settings.acceptance_window_minutes)
        ):
            return None
        self.generation += 1
        for index, row in enumerate(rows, 1):
            entity_id = str(row["entity_id"])
            self.exposures.append(
                Exposure(
                    timestamp=now,
                    entity_id=entity_id,
                    rank=int(row.get("rank", index)),
                    base_rank=(base_ranks or {}).get(entity_id, 0),
                    adaptive_rank=(adaptive_ranks or {}).get(
                        entity_id, int(row.get("rank", index))
                    ),
                    score=float(row.get("score", 0)),
                    context_hash=context_hash,
                    slot=int(row.get("slot", index)),
                    generation_id=self.generation,
                    source=source,
                    confidence=max(0.0, min(1.0, confidence)),
                    user_id=user_id,
                )
            )
            self.metrics["total_suggestions"] += 1
        self._last_exposure_fingerprint = fingerprint
        self._last_exposure_at = now
        self.last_learning_update = now
        return self.generation

    def _observe_feedback(self, exposure: Exposure, accepted: bool, moment: datetime) -> None:
        rank_weight = visibility_weight(exposure.rank)
        weight = exposure.confidence * rank_weight
        profiles = [GLOBAL_PROFILE]
        if exposure.user_id:
            profiles.append(exposure.user_id)
        for profile in profiles:
            for context_hash in ("*", exposure.context_hash):
                key = (profile, exposure.entity_id, context_hash)
                stat = self.feedback.get(key)
                if stat is None:
                    stat = self.feedback[key] = FeedbackStat(
                        profile, exposure.entity_id, context_hash
                    )
                stat.observe(accepted, weight, moment)

    def _expire_exposures(self, now: datetime, settings: AdaptiveSettings) -> int:
        cutoff = now - timedelta(minutes=settings.acceptance_window_minutes)
        expired = 0
        expired_generations: set[int] = set()
        for exposure in self.exposures:
            if not exposure.resolved and exposure.timestamp <= cutoff:
                exposure.resolved = True
                self._observe_feedback(exposure, False, now)
                self.metrics["ignored_suggestions"] += 1
                if not exposure.metric_counted:
                    expired_generations.add(exposure.generation_id)
                expired += 1
        for generation in expired_generations:
            rows = [row for row in self.exposures if row.generation_id == generation]
            if rows and not any(row.metric_counted for row in rows):
                self.metrics["prediction_windows"] += 1
                for row in rows:
                    row.metric_counted = True
        if expired:
            self.last_learning_update = now
        return expired

    def resolve_exposure(
        self,
        record: Usage,
        settings: AdaptiveSettings,
        *,
        now: datetime | None = None,
    ) -> int:
        """Resolve the newest matching active exposure as accepted."""
        if not settings.enabled or not settings.ignored_suggestion_learning:
            return 0
        moment = now or record.timestamp
        self._expire_exposures(moment, settings)
        window_start = moment - timedelta(minutes=settings.acceptance_window_minutes)
        matches = [
            exposure
            for exposure in self.exposures
            if not exposure.resolved
            and exposure.entity_id == record.entity_id
            and window_start <= exposure.timestamp <= moment
            and (exposure.user_id is None or exposure.user_id == record.user_id)
        ]
        if not matches:
            return 0
        exposure = max(matches, key=lambda row: row.timestamp)
        exposure.used = True
        exposure.resolved = True
        exposure.used_after_seconds = max(0.0, (moment - exposure.timestamp).total_seconds())
        if exposure.user_id is None and record.user_id:
            exposure.user_id = record.user_id
        self._observe_feedback(exposure, True, moment)
        self.metrics["accepted_suggestions"] += 1
        generation_rows = [
            row for row in self.exposures if row.generation_id == exposure.generation_id
        ]
        if not any(row.metric_counted for row in generation_rows):
            self.metrics["prediction_windows"] += 1
            self.metrics["top1_hits"] += exposure.rank == 1
            self.metrics["top3_hits"] += exposure.rank <= 3
            self.metrics["base_top3_hits"] += 0 < exposure.base_rank <= 3
            self.metrics["adaptive_top3_hits"] += 0 < exposure.adaptive_rank <= 3
            for row in generation_rows:
                row.metric_counted = True
        self.last_learning_update = moment
        return 1

    def _select_feedback(
        self,
        entity_id: str,
        context_hash: str,
        user_id: str | None,
        settings: AdaptiveSettings,
    ) -> FeedbackStat | None:
        def for_profile(profile: str) -> FeedbackStat | None:
            contextual = self.feedback.get((profile, entity_id, context_hash))
            aggregate = self.feedback.get((profile, entity_id, "*"))
            if contextual and contextual.exposures >= settings.minimum_exposures:
                return contextual
            return aggregate

        global_stat = for_profile(GLOBAL_PROFILE)
        user_stat = for_profile(user_id) if user_id else None
        if settings.learning_scope == "global":
            return global_stat
        if settings.learning_scope == "user":
            return user_stat
        if user_stat and user_stat.exposures >= settings.minimum_exposures:
            return user_stat
        return global_stat

    def feedback_signal(
        self,
        entity_id: str,
        context_hash: str,
        settings: AdaptiveSettings,
        *,
        user_id: str | None = None,
    ) -> FeedbackSignal:
        if not settings.enabled or not settings.ignored_suggestion_learning:
            return FeedbackSignal()
        stat = self._select_feedback(entity_id, context_hash, user_id, settings)
        if stat is None or stat.exposures == 0:
            return FeedbackSignal()
        acceptance_rate = (stat.accepted_weight + 2) / (stat.exposure_weight + 4)
        confidence = 1 - math.exp(-stat.exposures / max(1, settings.minimum_exposures))
        acceptance = max(0.0, (acceptance_rate - 0.5) * 2) * confidence
        ignored = 0.0
        if stat.exposures >= settings.minimum_exposures:
            ignored = max(0.0, (0.5 - acceptance_rate) * 2) * confidence
        return FeedbackSignal(
            acceptance_score=round(min(1.0, acceptance), 4),
            acceptance_rate=round(acceptance_rate, 4),
            ignore_penalty=round(min(1.0, ignored), 4),
            confidence=round(confidence, 4),
            exposures=stat.exposures,
        )

    def get_acceptance_score(
        self,
        entity_id: str,
        context_hash: str,
        settings: AdaptiveSettings,
        *,
        user_id: str | None = None,
    ) -> float:
        return self.feedback_signal(
            entity_id, context_hash, settings, user_id=user_id
        ).acceptance_score

    def get_ignore_penalty(
        self,
        entity_id: str,
        context_hash: str,
        settings: AdaptiveSettings,
        *,
        user_id: str | None = None,
    ) -> float:
        return self.feedback_signal(
            entity_id, context_hash, settings, user_id=user_id
        ).ignore_penalty

    def cleanup(
        self,
        now: datetime,
        retention_days: int,
        settings: AdaptiveSettings | None = None,
    ) -> int:
        if settings is not None:
            self._expire_exposures(now, settings)
        cutoff = now - timedelta(days=retention_days)
        stale = [
            key
            for key, stat in self.transitions.items()
            if stat.last_seen is None or stat.last_seen < cutoff
        ]
        for key in stale:
            del self.transitions[key]
        stale_chains = [
            key
            for key, stat in self.chains.items()
            if stat.last_seen is None or stat.last_seen < cutoff
        ]
        for chain_key in stale_chains:
            del self.chains[chain_key]
        cutoff = now - timedelta(days=retention_days)
        before = len(self.exposures)
        self.exposures = [row for row in self.exposures if row.timestamp >= cutoff]
        stale_feedback = [
            key
            for key, stat in self.feedback.items()
            if stat.last_seen is None or stat.last_seen < cutoff
        ]
        for key in stale_feedback:
            del self.feedback[key]
        return len(stale) + len(stale_chains) + before - len(self.exposures) + len(stale_feedback)

    def reset_sequence(self, *, entity_id: str | None = None, user_id: str | None = None) -> None:
        self.transitions = {
            key: stat
            for key, stat in self.transitions.items()
            if not (
                (entity_id is None or entity_id in (stat.from_entity, stat.to_entity))
                and (user_id is None or stat.profile == user_id)
            )
        }
        self.chains = {
            key: stat
            for key, stat in self.chains.items()
            if not (
                (
                    entity_id is None
                    or entity_id in (stat.first_entity, stat.second_entity, stat.to_entity)
                )
                and (user_id is None or stat.profile == user_id)
            )
        }
        if entity_id is None and user_id is None:
            self._recent_by_actor.clear()
            self._recent_global.clear()

    def reset_feedback(self, *, entity_id: str | None = None, user_id: str | None = None) -> None:
        self.feedback = {
            key: stat
            for key, stat in self.feedback.items()
            if not (
                (entity_id is None or stat.entity_id == entity_id)
                and (user_id is None or stat.profile == user_id)
            )
        }
        self.exposures = [
            row
            for row in self.exposures
            if not (
                (entity_id is None or row.entity_id == entity_id)
                and (user_id is None or row.user_id == user_id)
            )
        ]
        if entity_id is None and user_id is None:
            for key in self.metrics:
                self.metrics[key] = 0

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

    def top_chains(
        self, entity_id: str, *, user_id: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        profile = user_id or GLOBAL_PROFILE
        matches = [
            stat
            for stat in self.chains.values()
            if stat.profile == profile and stat.to_entity == entity_id
        ]
        matches.sort(key=lambda stat: (-stat.count, stat.first_entity, stat.second_entity))
        return [
            {
                "entities": [stat.first_entity, stat.second_entity],
                "count": stat.count,
                "confidence": round(1 - math.exp(-stat.count / 3), 4),
                "average_delay_seconds": round(stat.average_delay_seconds, 1),
                "median_delay_seconds": round(stat.median_delay_seconds, 1),
            }
            for stat in matches[:limit]
        ]

    def dashboard_snapshot(self, limit: int = 10) -> dict[str, Any]:
        """Return bounded global aggregates suitable for a local diagnostic card."""
        bounded = max(1, min(20, int(limit)))
        transitions = [stat for stat in self.transitions.values() if stat.profile == GLOBAL_PROFILE]
        transitions.sort(key=lambda stat: (-stat.count, stat.from_entity, stat.to_entity))
        chains = [stat for stat in self.chains.values() if stat.profile == GLOBAL_PROFILE]
        chains.sort(
            key=lambda stat: (-stat.count, stat.first_entity, stat.second_entity, stat.to_entity)
        )
        feedback = [
            stat
            for stat in self.feedback.values()
            if stat.profile == GLOBAL_PROFILE and stat.context_hash == "*"
        ]
        feedback.sort(key=lambda stat: (-stat.exposures, stat.entity_id))
        return {
            "top_transitions": [
                {
                    "from_entity_id": stat.from_entity,
                    "to_entity_id": stat.to_entity,
                    "count": stat.count,
                    "confidence": round(1 - math.exp(-stat.count / 3), 4),
                    "average_delay_seconds": round(stat.average_delay_seconds, 1),
                }
                for stat in transitions[:bounded]
            ],
            "top_sequences": [
                {
                    "entity_ids": [stat.first_entity, stat.second_entity, stat.to_entity],
                    "count": stat.count,
                    "confidence": round(1 - math.exp(-stat.count / 3), 4),
                    "average_delay_seconds": round(stat.average_delay_seconds, 1),
                }
                for stat in chains[:bounded]
            ],
            "entity_feedback": [
                {
                    "entity_id": stat.entity_id,
                    "suggestions": stat.exposures,
                    "accepted": stat.accepted,
                    "ignored": stat.ignored,
                    "acceptance_rate": round(
                        (stat.accepted_weight + 2) / (stat.exposure_weight + 4), 4
                    ),
                }
                for stat in feedback[:bounded]
            ],
        }

    def entity_feedback_stats(
        self, entity_id: str, *, user_id: str | None = None
    ) -> dict[str, Any]:
        profile = user_id or GLOBAL_PROFILE
        stat = self.feedback.get((profile, entity_id, "*"))
        if stat is None:
            return {
                "suggestions": 0,
                "accepted": 0,
                "ignored": 0,
                "acceptance_rate": 0.5,
            }
        return {
            "suggestions": stat.exposures,
            "accepted": stat.accepted,
            "ignored": stat.ignored,
            "acceptance_rate": round((stat.accepted_weight + 2) / (stat.exposure_weight + 4), 4),
        }

    def counts(self) -> dict[str, Any]:
        supported = sum(1 for stat in self.transitions.values() if stat.count >= 3)
        supported_chains = sum(1 for stat in self.chains.values() if stat.count >= 3)
        return {
            "sequence_patterns": len(self.transitions),
            "supported_sequence_patterns": supported,
            "sequence_chain_patterns": len(self.chains),
            "supported_sequence_chain_patterns": supported_chains,
            "suggestion_exposures": len(self.exposures),
            "feedback_patterns": len(self.feedback),
            "adaptive_rejected_records": self.rejected,
            **self.metrics_snapshot(),
        }

    def metrics_snapshot(self) -> dict[str, Any]:
        windows = self.metrics["prediction_windows"]
        total = self.metrics["total_suggestions"]
        learning_evidence = (
            sum(stat.count for stat in self.transitions.values())
            + sum(stat.count for stat in self.chains.values())
            + sum(stat.exposures for stat in self.feedback.values() if stat.context_hash == "*")
        )
        return {
            **self.metrics,
            "top1_hit_rate": round(self.metrics["top1_hits"] / windows, 4) if windows else 0.0,
            "top3_hit_rate": round(self.metrics["top3_hits"] / windows, 4) if windows else 0.0,
            "base_top3_hit_rate": round(self.metrics["base_top3_hits"] / windows, 4)
            if windows
            else 0.0,
            "adaptive_top3_hit_rate": round(self.metrics["adaptive_top3_hits"] / windows, 4)
            if windows
            else 0.0,
            "accepted_rate": round(self.metrics["accepted_suggestions"] / total, 4)
            if total
            else 0.0,
            "learning_confidence": round(1 - math.exp(-learning_evidence / 20), 4),
            "last_learning_update": self.last_learning_update.isoformat()
            if self.last_learning_update
            else None,
        }

    @staticmethod
    def get_predictive_score(
        base_score: float,
        sequence_score: float,
        acceptance_score: float,
        ignore_penalty: float,
        settings: AdaptiveSettings,
    ) -> float:
        sequence_weight = max(0.0, min(1.0, settings.sequence_influence / 100))
        acceptance_weight = max(0.0, min(1.0, settings.acceptance_boost / 100))
        penalty_weight = max(0.0, min(1.0, settings.ignored_penalty_strength / 100))
        prediction_weight = max(0.0, min(1.0, settings.prediction_influence / 100))
        target = (
            base_score
            + sequence_weight * sequence_score * (1 - base_score)
            + acceptance_weight * acceptance_score * (1 - base_score)
            - penalty_weight * ignore_penalty * base_score
        )
        target = max(0.0, min(1.0, target))
        return round(max(0.0, min(1.0, base_score + prediction_weight * (target - base_score))), 4)

    def apply_adaptive(
        self,
        ranked: list[Ranked],
        now: datetime,
        settings: AdaptiveSettings,
        user_id: str | None = None,
        presence_home: bool | None = None,
        context_hash: str = "*",
    ) -> list[Ranked]:
        """Blend bounded sequence and feedback signals after the base scorer."""
        if not settings.enabled:
            return [replace(item, base_score=item.score) for item in ranked]
        result: list[Ranked] = []
        for item in ranked:
            signal = self.get_sequence_score(
                item.entity_id,
                now,
                settings,
                user_id=user_id,
                presence_home=presence_home,
            )
            feedback = self.feedback_signal(item.entity_id, context_hash, settings, user_id=user_id)
            final = self.get_predictive_score(
                item.score,
                signal.score,
                feedback.acceptance_score,
                feedback.ignore_penalty,
                settings,
            )
            reason = (
                "sequence_chain_habit"
                if signal.depth == 2 and signal.score > 0.25
                else "sequence_habit"
                if signal.score > 0.25
                else "accepted_habit"
                if feedback.acceptance_score > 0.2
                else item.reason_key
            )
            result.append(
                replace(
                    item,
                    score=final,
                    reason_key=reason,
                    source=(
                        "adaptive"
                        if signal.score or feedback.acceptance_score or feedback.ignore_penalty
                        else item.source
                    ),
                    base_score=item.score,
                    sequence_score=signal.score,
                    sequence_depth=signal.depth,
                    acceptance_score=feedback.acceptance_score,
                    acceptance_rate=feedback.acceptance_rate,
                    ignore_penalty=feedback.ignore_penalty,
                    adaptive_confidence=max(signal.confidence, feedback.confidence),
                )
            )
        return sorted(result, key=lambda item: (-item.score, item.entity_id))

    def apply_sequence(
        self,
        ranked: list[Ranked],
        now: datetime,
        settings: AdaptiveSettings,
        user_id: str | None = None,
        presence_home: bool | None = None,
    ) -> list[Ranked]:
        """Compatibility wrapper retained for focused sequence tests."""
        return self.apply_adaptive(ranked, now, settings, user_id, presence_home)
