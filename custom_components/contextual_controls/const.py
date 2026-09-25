"""Shared constants; no Home Assistant imports."""

DOMAIN = "contextual_controls"
VERSION = "0.3.0"
NAME = "Contextual Controls"
STORAGE_VERSION = 3
MAX_RECORDS = 50_000
RETENTION_DAYS = 90
DEFAULT_DOMAINS = ["light", "switch", "cover", "climate", "media_player", "scene", "script"]
SUPPORTED_DOMAINS = DEFAULT_DOMAINS + [
    "fan",
    "lock",
    "button",
    "input_boolean",
    "vacuum",
    "select",
    "number",
]
DEFAULTS = {
    "included_entities": [],
    "included_domains": DEFAULT_DOMAINS,
    "excluded_entities": [],
    "excluded_domains": [],
    "all_areas": True,
    "included_areas": [],
    "excluded_areas": [],
    "suggestion_count": 6,
    "learning_period_days": 21,
    "time_window_minutes": 90,
    "recency_weight": 70,
    "learn_sources": ["manual", "assist"],
    "user_id": "",
    "consider_weekday": True,
    "weekday_mode": "workweek",
    "presence_entities": [],
    "presence_mode": "signal",
    "context_entities": [],
    "ignored_entities": [],
    "pinned_entities": [],
    "pinned_position": "before",
    "pinned_use_slots": True,
    "refresh_minutes": 15,
    "minimum_confidence": 20,
    "cold_start": "recent",
    "debug": False,
}

PRESENCE_DOMAINS = ["person", "device_tracker", "binary_sensor"]
LEARNING_SOURCES = ["manual", "assist", "automation", "script", "unknown"]
