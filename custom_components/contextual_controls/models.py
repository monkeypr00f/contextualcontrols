"""Immutable data crossing collection, storage and scoring boundaries."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Usage:
    timestamp: datetime
    entity_id: str
    user_id: str | None
    source: str
    action: str
    confidence: float
    area_id: str | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    entity_id: str
    state: str
    area_id: str | None = None
    disabled: bool = False


@dataclass(frozen=True, slots=True)
class Ranked:
    entity_id: str
    score: float
    reason_key: str
    count: int = 0
    source: str = "statistical"
    pinned: bool = False
    frequency: float = 0.0
    time: float = 0.0
    recency: float = 0.0
    confidence: float = 0.0
    current_state: float = 1.0


@dataclass(frozen=True, slots=True)
class ScoringSettings:
    learning_period_days: int = 21
    time_window_minutes: int = 90
    recency_weight: float = 70
    minimum_confidence: float = 20
    cold_start: str = "recent"
    user_id: str = ""
    learn_sources: tuple[str, ...] = ("user",)
    ignored_entities: tuple[str, ...] = ()
