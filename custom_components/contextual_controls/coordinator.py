"""Home Assistant event ingestion and snapshot-based statistical evaluation."""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_CALL_SERVICE,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DEFAULTS, DOMAIN
from .eligibility import compose, eligible
from .models import Candidate, ScoringSettings, Usage
from .scoring import rank
from .storage import History
from .tracking import ACTIONS, Deduplicator, classify, supports_action

_LOGGER = logging.getLogger(__name__)


class ContextualCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.options = {**DEFAULTS, **entry.options}
        interval = int(self.options["refresh_minutes"])
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(minutes=interval) if interval else None,
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=5, immediate=False),
        )
        self.history = History(hass, entry.entry_id)
        self.eligible_ids: set[str] = set()
        self.areas: dict[str, str | None] = {}
        self._dirty = True
        self._unsubscribers: list = []
        self._pending_refresh = None
        self._closed = False
        self._dedup = Deduplicator()
        self._translations: dict[str, str] = {}

    async def async_initialize(self) -> None:
        await self.history.async_load(dt_util.utcnow())
        self._translations = await async_get_translations(
            self.hass, self.hass.config.language, "entity", {DOMAIN}
        )
        self._rebuild()
        for event_type, listener in (
            (EVENT_CALL_SERVICE, self._service),
            (EVENT_STATE_CHANGED, self._state),
            (EVENT_HOMEASSISTANT_STARTED, self._topology),
            (er.EVENT_ENTITY_REGISTRY_UPDATED, self._topology),
            (dr.EVENT_DEVICE_REGISTRY_UPDATED, self._topology),
            (ar.EVENT_AREA_REGISTRY_UPDATED, self._topology),
        ):
            self._unsubscribers.append(self.hass.bus.async_listen(event_type, listener))

    @callback
    def _rebuild(self) -> None:
        entities = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        self.eligible_ids.clear()
        self.areas.clear()
        for state in self.hass.states.async_all():
            entry = entities.async_get(state.entity_id)
            area = entry.area_id if entry else None
            if not area and entry and entry.device_id:
                device = devices.async_get(entry.device_id)
                area = device.area_id if device else None
            candidate = Candidate(
                state.entity_id, state.state, area, bool(entry and entry.disabled_by)
            )
            if eligible(candidate, self.options):
                self.eligible_ids.add(state.entity_id)
                self.areas[state.entity_id] = area
        self._dirty = False

    @callback
    def _request(self) -> None:
        if self._closed or self._pending_refresh is not None:
            return
        self._pending_refresh = async_call_later(self.hass, 2, self._refresh)

    async def _refresh(self, _now) -> None:
        self._pending_refresh = None
        if not self._closed:
            await self.async_request_refresh()

    @callback
    def _topology(self, _event: Event) -> None:
        self._dirty = True
        self._request()

    @callback
    def _state(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        if event.data.get("old_state") is None or event.data.get("new_state") is None:
            # Index updates only for supported domains; sensor writes don't loop.
            if entity_id.partition(".")[0] in ACTIONS:
                self._dirty = True
                self._request()
        elif entity_id in self.eligible_ids:
            self._request()

    @callback
    def _service(self, event: Event) -> None:
        domain = event.data.get("domain")
        action = event.data.get("service")
        if domain not in ACTIONS and domain != "homeassistant":
            return
        source, confidence = classify(event.context.user_id, event.context.parent_id)
        if source not in self.options["learn_sources"]:
            return
        if self.options["user_id"] and self.options["user_id"] != event.context.user_id:
            return
        if self._dirty:
            self._rebuild()
        service_data = event.data.get("service_data", {})
        if not isinstance(service_data, dict) or not isinstance(action, str):
            return
        if domain == "script" and action not in ACTIONS["script"]:
            targets = {f"script.{action}"}
            action = "turn_on"
        else:
            # Ignore malformed synthetic bus events, without breaking HA's event loop.
            try:
                selection = TargetSelection(service_data)
                selected = async_extract_referenced_entity_ids(self.hass, selection)
                targets = selected.referenced | selected.indirectly_referenced
                if "all" in selection.entity_ids:
                    targets = self.eligible_ids.copy()
            except TypeError, ValueError, KeyError:
                _LOGGER.debug("Ignoring invalid service target")
                return
        now = dt_util.utcnow()
        for entity_id in targets & self.eligible_ids:
            if entity_id in self.options["ignored_entities"] or not supports_action(
                entity_id, domain, action
            ):
                continue
            if self._dedup.accept(event.context.id, entity_id, action, now.timestamp()):
                self.history.append(
                    Usage(
                        now,
                        entity_id,
                        event.context.user_id,
                        source,
                        action,
                        confidence,
                        self.areas.get(entity_id),
                    )
                )
                self._request()

    async def _async_update_data(self) -> dict[str, Any]:
        if self._dirty:
            self._rebuild()
        now = dt_util.now()
        self.history.prune(now)
        self.history.schedule_save()
        candidates = {
            entity_id: Candidate(entity_id, state.state, self.areas.get(entity_id))
            for entity_id in self.eligible_ids
            if (state := self.hass.states.get(entity_id))
        }
        settings = ScoringSettings(
            **{
                key: self.options[key]
                for key in (
                    "learning_period_days",
                    "time_window_minutes",
                    "recency_weight",
                    "minimum_confidence",
                    "cold_start",
                    "user_id",
                    "learn_sources",
                    "ignored_entities",
                )
            }
        )
        ranked = await self.hass.async_add_executor_job(
            rank, tuple(candidates.values()), tuple(self.history.records), now, settings
        )
        selected = compose(ranked, candidates, self.options)
        rows = []
        for index, item in enumerate(selected, 1):
            key = (
                f"component.{DOMAIN}.entity.sensor.suggestions.state_attributes.reason.state."
                f"{item.reason_key}"
            )
            rows.append(
                {
                    "entity_id": item.entity_id,
                    "score": item.score,
                    "reason": self._translations.get(key, item.reason_key),
                    "source": item.source,
                    "rank": index,
                    "pinned": item.pinned,
                    "usage_count_in_window": item.count,
                }
            )
        result = {
            "entities": rows,
            "last_update": now.isoformat(),
            "mode": "statistical",
            "ai_used": False,
            "learning_period_days": settings.learning_period_days,
            "candidate_count": len(ranked),
            **self.history.counts(),
        }
        if self.options["debug"]:
            result["candidate_scores"] = {
                item.entity_id: {
                    "frequency": item.frequency,
                    "time": item.time,
                    "recency": item.recency,
                    "confidence": item.confidence,
                    "current_state": item.current_state,
                    "final": item.score,
                }
                for item in ranked[:30]
            }
        return result

    async def async_close(self) -> None:
        self._closed = True
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._pending_refresh:
            self._pending_refresh()
            self._pending_refresh = None
        await self.async_shutdown()
        await self.history.async_flush()
