"""Shared constants; no Home Assistant imports."""

DOMAIN = "contextual_controls"
VERSION = "0.6.0"
NAME = "Contextual Controls"
STORAGE_VERSION = 4
MAX_RECORDS = 50_000
RETENTION_DAYS = 90
DEFAULT_DOMAINS = ["light", "switch", "cover", "climate", "media_player", "scene", "script"]
SUPPORTED_DOMAINS = DEFAULT_DOMAINS + [
    "fan",
    "lock",
    "button",
    "input_button",
    "input_boolean",
    "vacuum",
    "select",
    "number",
    "alarm_control_panel",
    "siren",
]
DEFAULTS = {
    "mode": "hybrid",
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
    "ai_provider": "disabled",
    "candidate_pool_size": 15,
    "ai_min_refresh_minutes": 15,
    "ai_timeout_seconds": 15,
    "ai_temperature": 0.1,
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.2",
    "openai_endpoint": "https://api.openai.com",
    "openai_model": "gpt-4.1-mini",
    "ai_share_entity_id": True,
    "ai_share_friendly_name": True,
    "ai_share_current_state": True,
    "ai_share_area": True,
    "ai_share_usage_statistics": True,
    "ai_share_exact_timestamps": False,
    "ai_share_presence_information": False,
    "ai_share_context_entities": True,
    "quick_access_enabled": True,
    "quick_access_slots": 6,
    "quick_access_safety_mode": "safe",
    "quick_access_stability": "120",
    "quick_access_sensitive_entities": [],
    "quick_access_response": True,
    "quick_access_track_usage": True,
    "quick_access_usage_weight": 100,
}

PRESENCE_DOMAINS = ["person", "device_tracker", "binary_sensor"]
LEARNING_SOURCES = ["manual", "assist", "automation", "script", "unknown"]
AI_PROVIDERS = ["disabled", "ollama", "openai_compatible"]
MODES = ["hybrid", "statistical", "ai_assisted"]
QUICK_ACCESS_SAFETY_MODES = ["safe", "balanced", "direct"]
QUICK_ACCESS_STABILITY = ["0", "30", "60", "120", "300"]
