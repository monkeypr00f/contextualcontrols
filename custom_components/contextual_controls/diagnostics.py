"""Counts only: no identities, entity names, raw history or user IDs."""

from collections import Counter

from .const import VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    options = coordinator.options
    sources = Counter(record.source for record in coordinator.history.records)
    return {
        "version": VERSION,
        "mode": "statistical",
        "ai_provider": "disabled",
        "ai_status": "not_configured",
        "eligible_entities_count": len(coordinator.eligible_ids),
        **coordinator.history.counts(),
        "last_evaluation_date": (coordinator.data or {}).get("last_update", "")[:10],
        "learning_records_by_source": dict(sorted(sources.items())),
        "presence_entities_count": len(options["presence_entities"]),
        "context_entities_count": len(options["context_entities"]),
        "configuration": {
            key: options[key]
            for key in (
                "learning_period_days",
                "time_window_minutes",
                "recency_weight",
                "suggestion_count",
                "refresh_minutes",
                "minimum_confidence",
                "cold_start",
                "consider_weekday",
                "weekday_mode",
                "presence_mode",
            )
        },
    }
