"""Counts only: no identities, entity names, raw history or user IDs."""

from .const import VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    options = coordinator.options
    return {
        "version": VERSION,
        "mode": "statistical",
        "ai_provider": "disabled",
        "eligible_entities_count": len(coordinator.eligible_ids),
        **coordinator.history.counts(),
        "last_evaluation_date": (coordinator.data or {}).get("last_update", "")[:10],
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
            )
        },
    }
