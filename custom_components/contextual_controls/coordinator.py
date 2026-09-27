"""Home Assistant event ingestion, ranking and cached quick-access execution."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.automation import EVENT_AUTOMATION_TRIGGERED
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.components.script.const import EVENT_SCRIPT_STARTED
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_CALL_SERVICE,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
)
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .ai import (
    AIManager,
    AIReranker,
    OllamaProvider,
    OpenAICompatibleProvider,
    PrivacySettings,
    build_prompt,
)
from .const import DEFAULTS, DOMAIN
from .context import is_home, presence_status, snapshot_context
from .eligibility import available, compose, eligible
from .models import Candidate, ScoringSettings, Usage
from .quick_access import (
    DEFAULT_ICONS,
    QUICK_ACCESS_SOURCES,
    SlotManager,
    resolve_default_action,
    safety_rejection,
)
from .scoring import rank
from .storage import History
from .tracking import ACTIONS, Deduplicator, OriginTracker, classify, supports_action

_LOGGER = logging.getLogger(__name__)


class ContextualCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
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
        self.signal_areas: dict[str, str | None] = {}
        self._dirty = True
        self._unsubscribers: list = []
        self._pending_refresh = None
        self._closed = False
        self._dedup = Deduplicator()
        self._origins = OriginTracker()
        self._translations: dict[str, str] = {}
        self._ai_manager: AIManager | None = None
        self._ai_last_update: datetime | None = None
        self._ai_status = "disabled"
        self.slot_manager = SlotManager(
            int(self.options["quick_access_slots"]),
            int(self.options["quick_access_stability"]),
        )
        self._quick_access_lock = asyncio.Lock()
        self._quick_access_contexts: set[str] = set()
        self.quick_access_executions = 0
        self.stale_slot_rejections = 0
        self.sensitive_action_rejections = 0

    async def async_initialize(self) -> None:
        await self.history.async_load(dt_util.utcnow())
        self._translations = await async_get_translations(
            self.hass, self.hass.config.language, "entity", {DOMAIN}
        )
        self._initialize_ai()
        self._rebuild()
        for event_type, listener in (
            (EVENT_CALL_SERVICE, self._service),
            (EVENT_STATE_CHANGED, self._state),
            (EVENT_HOMEASSISTANT_STARTED, self._topology),
            (EVENT_AUTOMATION_TRIGGERED, self._automation),
            (EVENT_SCRIPT_STARTED, self._script_started),
            (er.EVENT_ENTITY_REGISTRY_UPDATED, self._topology),
            (dr.EVENT_DEVICE_REGISTRY_UPDATED, self._topology),
            (ar.EVENT_AREA_REGISTRY_UPDATED, self._topology),
        ):
            self._unsubscribers.append(self.hass.bus.async_listen(event_type, listener))

    def _initialize_ai(self) -> None:
        provider_name = self.options["ai_provider"]
        if provider_name == "disabled":
            return
        self._ai_status = "ready"

    def _ensure_ai_manager(self) -> None:
        if self._ai_manager is not None or self.options["ai_provider"] == "disabled":
            return
        provider_name = self.options["ai_provider"]
        session = async_get_clientsession(self.hass)
        common = (
            session,
            self.options["ollama_url" if provider_name == "ollama" else "openai_endpoint"],
            self.options["ollama_model" if provider_name == "ollama" else "openai_model"],
            self.options["ai_timeout_seconds"],
            self.options["ai_temperature"],
        )
        if provider_name == "ollama":
            provider: AIReranker = OllamaProvider(*common)
        else:
            provider = OpenAICompatibleProvider(*common, self.entry.data.get("openai_api_key", ""))
        self._ai_manager = AIManager(provider, self.options["ai_min_refresh_minutes"])

    @callback
    def _rebuild(self) -> None:
        entities = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        self.eligible_ids.clear()
        self.areas.clear()
        self.signal_areas.clear()
        signal_ids = set(self.options["presence_entities"]) | set(self.options["context_entities"])
        for state in self.hass.states.async_all():
            entry = entities.async_get(state.entity_id)
            area = entry.area_id if entry else None
            if not area and entry and entry.device_id:
                device = devices.async_get(entry.device_id)
                area = device.area_id if device else None
            candidate = Candidate(
                state.entity_id, state.state, area, bool(entry and entry.disabled_by)
            )
            if state.entity_id in signal_ids:
                self.signal_areas[state.entity_id] = area
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
        elif entity_id in self.eligible_ids or entity_id in set(
            self.options["presence_entities"] + self.options["context_entities"]
        ):
            self._request()

    @callback
    def _automation(self, event: Event) -> None:
        self._origins.observe(event.context.id, "automation", event.time_fired.timestamp())

    @callback
    def _script_started(self, event: Event) -> None:
        self._origins.observe(event.context.id, "script", event.time_fired.timestamp())

    @callback
    def _signal_snapshot(
        self,
    ) -> tuple[bool | None, tuple[tuple[str, str], ...], tuple[str, ...]]:
        presence_ids = tuple(self.options["presence_entities"])
        context_ids = tuple(self.options["context_entities"])
        signal_ids = set(presence_ids) | set(context_ids)
        states = {
            entity_id: state.state
            for entity_id in signal_ids
            if (state := self.hass.states.get(entity_id))
        }
        presence = presence_status(states, presence_ids)
        context = snapshot_context(states, context_ids)
        active_areas = tuple(
            sorted(
                {
                    area_id
                    for entity_id in presence_ids
                    if (area_id := self.signal_areas.get(entity_id))
                    and is_home(entity_id, states.get(entity_id, "unknown"))
                }
            )
        )
        return presence, context, active_areas

    @callback
    def _service(self, event: Event) -> None:
        domain = event.data.get("domain")
        action = event.data.get("service")
        if domain == "conversation" and action == "process":
            self._origins.observe(event.context.id, "assist", event.time_fired.timestamp())
            return
        if event.context.id in self._quick_access_contexts:
            return
        if domain not in ACTIONS and domain != "homeassistant":
            return
        source, confidence = classify(
            event.context.id,
            event.context.user_id,
            event.context.parent_id,
            self._origins,
        )
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
        presence, context, _active_areas = self._signal_snapshot()
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
                        presence,
                        context,
                    )
                )
                self._request()

    async def _async_update_data(self) -> dict[str, Any]:
        if self._dirty:
            self._rebuild()
        now = dt_util.now()
        presence, context, active_areas = self._signal_snapshot()
        self.history.prune(now)
        self.history.schedule_save()
        candidates = {
            entity_id: Candidate(entity_id, state.state, self.areas.get(entity_id))
            for entity_id in self.eligible_ids
            if (state := self.hass.states.get(entity_id))
        }
        learn_sources = list(self.options["learn_sources"])
        if self.options["quick_access_track_usage"]:
            learn_sources.append("quick_access")
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
                    "ignored_entities",
                    "consider_weekday",
                    "weekday_mode",
                    "presence_mode",
                )
            },
            learn_sources=tuple(dict.fromkeys(learn_sources)),
            presence_home=presence,
            active_area_ids=active_areas,
            context_states=context,
        )
        ai_used = False
        ai_cached = False
        ai_error = None
        if self.options["presence_mode"] == "require_home" and presence is not True:
            ranked = []
            selected = []
        else:
            ranked = await self.hass.async_add_executor_job(
                rank, tuple(candidates.values()), tuple(self.history.records), now, settings
            )
            if (
                self.options["ai_provider"] != "disabled"
                and self.options["mode"] != "statistical"
                and ranked
            ):
                self._ensure_ai_manager()
                assert self._ai_manager is not None
                pool_size = int(self.options["candidate_pool_size"])
                shortlist = ranked[:pool_size]
                area_registry = ar.async_get(self.hass)
                prompt_rows = []
                for item in shortlist:
                    state = self.hass.states.get(item.entity_id)
                    area_id = self.areas.get(item.entity_id)
                    area_entry = area_registry.async_get_area(area_id) if area_id else None
                    prompt_rows.append(
                        {
                            "entity_id": item.entity_id,
                            "friendly_name": state.attributes.get("friendly_name")
                            if state
                            else None,
                            "state": state.state if state else None,
                            "area": area_entry.name if area_entry else area_id,
                            "score": item.score,
                            "count": item.count,
                            "reason": item.reason_key,
                        }
                    )
                privacy = PrivacySettings(
                    entity_id=self.options["ai_share_entity_id"],
                    friendly_name=self.options["ai_share_friendly_name"],
                    current_state=self.options["ai_share_current_state"],
                    area=self.options["ai_share_area"],
                    usage_statistics=self.options["ai_share_usage_statistics"],
                    exact_timestamps=self.options["ai_share_exact_timestamps"],
                    presence_information=self.options["ai_share_presence_information"],
                    context_entities=self.options["ai_share_context_entities"],
                )
                context_rows = []
                for index, (entity_id, state_value) in enumerate(context, 1):
                    state = self.hass.states.get(entity_id)
                    if privacy.entity_id:
                        label = entity_id
                    elif privacy.friendly_name and state:
                        label = state.attributes.get("friendly_name", f"context_{index}")
                    else:
                        label = f"context_{index}"
                    context_rows.append({"id": label, "state": state_value})
                package = build_prompt(
                    now,
                    prompt_rows,
                    privacy,
                    presence_home=presence,
                    context_states=context_rows,
                )
                outcome = await self._ai_manager.async_rerank(
                    package, shortlist, self.options["mode"], now
                )
                ranked = outcome.ranked + ranked[pool_size:]
                ai_used = outcome.used
                ai_cached = outcome.cached
                ai_error = outcome.error
                if outcome.last_update is not None:
                    self._ai_last_update = outcome.last_update
                self._ai_status = (
                    "cached"
                    if outcome.cached
                    else "used"
                    if outcome.used
                    else "throttled"
                    if outcome.error == "minimum_refresh_interval"
                    else "error"
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
        if self.options["quick_access_enabled"]:
            self.slot_manager.update(rows, now, self._quick_target_valid)
        else:
            self.slot_manager.clear(now)
        result = {
            "entities": rows,
            "last_update": now.isoformat(),
            "mode": self.options["mode"],
            "ai_used": ai_used,
            "ai_cached": ai_cached,
            "ai_provider": self.options["ai_provider"],
            "ai_status": self._ai_status,
            "last_ai_update": self._ai_last_update.isoformat() if self._ai_last_update else None,
            "learning_period_days": settings.learning_period_days,
            "candidate_count": len(ranked),
            "presence_mode": self.options["presence_mode"],
            "presence_home": presence,
            "context_entities_count": len(context),
            "active_areas_count": len(active_areas),
            "quick_access_enabled": self.options["quick_access_enabled"],
            "quick_access_slots": int(self.options["quick_access_slots"]),
            "slot_generation": self.slot_manager.generation,
            "last_slot_refresh": self.slot_manager.last_refresh.isoformat()
            if self.slot_manager.last_refresh
            else None,
            **self.history.counts(),
        }
        if ai_error is not None:
            result["ai_error"] = ai_error
        if self.options["debug"]:
            result["candidate_scores"] = {
                item.entity_id: {
                    "frequency": item.frequency,
                    "time": item.time,
                    "recency": item.recency,
                    "confidence": item.confidence,
                    "current_state": item.current_state,
                    "weekday": item.weekday,
                    "presence": item.presence,
                    "area": item.area,
                    "context": item.context,
                    "final": item.score,
                }
                for item in ranked[:30]
            }
        return result

    @callback
    def _quick_target_valid(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        if entity_id not in self.eligible_ids or state is None:
            return False
        return available(Candidate(entity_id, state.state, self.areas.get(entity_id)))

    @callback
    def quick_access_slot(self, slot: int) -> dict[str, Any]:
        """Return a slot from coordinator memory without triggering a refresh."""
        snapshot = self.slot_manager.get(slot)
        if snapshot is None:
            return {"slot": slot, "success": False, "reason": "empty_slot", "available": False}
        state = self.hass.states.get(snapshot.entity_id)
        if state is None or not self._quick_target_valid(snapshot.entity_id):
            return {
                "slot": slot,
                "entity_id": snapshot.entity_id,
                "success": False,
                "reason": "unavailable_target",
                "available": False,
                "slot_generation_id": self.slot_manager.generation,
            }
        domain = snapshot.entity_id.partition(".")[0]
        supported = int(state.attributes.get("supported_features", 0) or 0)
        media_mask = int(MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PAUSE)
        action = resolve_default_action(snapshot.entity_id, state.state, supported, media_mask)
        return {
            "slot": slot,
            "entity_id": snapshot.entity_id,
            "name": state.attributes.get("friendly_name", snapshot.entity_id),
            "icon": state.attributes.get("icon") or DEFAULT_ICONS.get(domain),
            "state": state.state,
            "domain": domain,
            "recommended_action": action.name if action else "more_info",
            "score": snapshot.score,
            "reason": snapshot.reason,
            "source": snapshot.source,
            "pinned": snapshot.pinned,
            "available": True,
            "slot_generation_id": self.slot_manager.generation,
            "slot_updated_at": snapshot.changed_at.isoformat(),
        }

    async def async_execute_slot(
        self,
        slot: int,
        *,
        expected_entity_id: str | None,
        mode: str,
        confirmed: bool,
        source: str,
        context: Context,
    ) -> dict[str, Any]:
        """Execute a cached slot; never refresh ranking or call an AI provider."""
        async with self._quick_access_lock:
            if not self.options["quick_access_enabled"]:
                return {"slot": slot, "success": False, "reason": "quick_access_disabled"}
            if not 1 <= slot <= int(self.options["quick_access_slots"]):
                return {"slot": slot, "success": False, "reason": "invalid_slot"}
            result = self.quick_access_slot(slot)
            if not result.get("available"):
                return result
            entity_id = result["entity_id"]
            if expected_entity_id and expected_entity_id != entity_id:
                self.stale_slot_rejections += 1
                return {
                    "slot": slot,
                    "entity_id": entity_id,
                    "success": False,
                    "reason": "stale_slot",
                }
            rejection = safety_rejection(
                entity_id,
                self.options["quick_access_safety_mode"],
                self.options["quick_access_sensitive_entities"],
                confirmed,
            )
            if rejection:
                self.sensitive_action_rejections += 1
                return {
                    "slot": slot,
                    "entity_id": entity_id,
                    "name": result["name"],
                    "success": False,
                    "reason": rejection,
                    "requires_confirmation": True,
                }
            if mode == "more_info":
                return {
                    "slot": slot,
                    "entity_id": entity_id,
                    "name": result["name"],
                    "success": False,
                    "reason": "requires_app",
                }
            state = self.hass.states.get(entity_id)
            assert state is not None
            supported = int(state.attributes.get("supported_features", 0) or 0)
            media_mask = int(MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PAUSE)
            action = resolve_default_action(entity_id, state.state, supported, media_mask)
            if action is None or not self.hass.services.has_service(action.domain, action.service):
                return {
                    "slot": slot,
                    "entity_id": entity_id,
                    "name": result["name"],
                    "success": False,
                    "reason": "unsupported_action",
                }
            self._quick_access_contexts.add(context.id)
            try:
                try:
                    await self.hass.services.async_call(
                        action.domain,
                        action.service,
                        {"entity_id": entity_id},
                        blocking=True,
                        context=context,
                    )
                except HomeAssistantError:
                    return {
                        "slot": slot,
                        "entity_id": entity_id,
                        "name": result["name"],
                        "success": False,
                        "reason": "service_error",
                    }
            finally:
                self._quick_access_contexts.discard(context.id)
            if self.options["quick_access_track_usage"]:
                now = dt_util.utcnow()
                presence, context_states, _active_areas = self._signal_snapshot()
                self.history.append(
                    Usage(
                        now,
                        entity_id,
                        context.user_id,
                        "quick_access",
                        action.service,
                        float(self.options["quick_access_usage_weight"]) / 100,
                        self.areas.get(entity_id),
                        presence,
                        context_states,
                        source if source in QUICK_ACCESS_SOURCES else "unknown",
                    )
                )
                self._request()
            self.quick_access_executions += 1
            return {
                "slot": slot,
                "entity_id": entity_id,
                "name": result["name"],
                "action": action.name,
                "success": True,
                "slot_generation_id": self.slot_manager.generation,
            }

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
