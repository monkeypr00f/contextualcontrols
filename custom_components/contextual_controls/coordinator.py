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

from .adaptive import AdaptiveSettings, context_fingerprint
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
from .location import LocationEngine, TrackerObservation
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
from .terminal import TerminalManager
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
        self.location = LocationEngine()
        self._location_timer = None
        self.terminal_manager = TerminalManager(hass, self)

    async def async_initialize(self) -> None:
        await self.history.async_load(dt_util.utcnow())
        self.location = LocationEngine(self.history.location_data["observed_access_points"])
        self.location.configure(self.options["location_contexts"])
        self._translations = await async_get_translations(
            self.hass, self.hass.config.language, "entity", {DOMAIN}
        )
        self._initialize_ai()
        self._rebuild()
        self._unsubscribers.append(self.async_add_listener(self._publish_terminals))
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

    @callback
    def _publish_terminals(self) -> None:
        """Mirror a completed ranking to configured physical terminals."""
        if self.terminal_manager.sessions:
            self.hass.async_create_task(self.terminal_manager.async_publish_all())

    def _initialize_ai(self) -> None:
        provider_name = self.options["ai_provider"]
        if provider_name == "disabled":
            return
        self._ai_status = "ready"

    def _adaptive_settings(self) -> AdaptiveSettings:
        source_weights = {
            name: float(self.options[f"adaptive_weight_{name}"]) / 100
            for name in (
                "manual",
                "assist",
                "quick_access",
                "apple_watch",
                "shortcut",
                "script",
                "automation",
                "unknown",
            )
        }
        return AdaptiveSettings(
            enabled=self.options["adaptive_learning"],
            sequence_enabled=self.options["sequence_learning"],
            sequence_window_minutes=int(self.options["sequence_window_minutes"]),
            sequence_influence=float(self.options["sequence_influence"]),
            minimum_transition_occurrences=int(self.options["minimum_transition_occurrences"]),
            sequence_decay_days=int(self.options["sequence_decay_days"]),
            prediction_influence=float(self.options["prediction_influence"]),
            learning_scope=self.options["learning_scope"],
            retention_days=int(self.options["adaptive_retention_days"]),
            ignored_suggestion_learning=self.options["ignored_suggestion_learning"],
            acceptance_window_minutes=int(self.options["suggestion_acceptance_window_minutes"]),
            minimum_exposures=int(self.options["minimum_exposures"]),
            ignored_penalty_strength=float(self.options["ignored_suggestion_penalty"]),
            acceptance_boost=float(self.options["acceptance_boost"]),
            source_weights=source_weights,
        )

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
        signal_ids = (
            set(self.options["presence_entities"])
            | set(self.options["context_entities"])
            | set(self.options["location_trackers"])
        )
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
            self.options["presence_entities"]
            + self.options["context_entities"]
            + self.options["location_trackers"]
        ):
            self._request()

    @callback
    def _location_refresh(self, _now) -> None:
        self._location_timer = None
        self._request()

    @callback
    def _update_location(self, now: datetime):
        trackers = tuple(self.options["location_trackers"])
        observations = []
        for entity_id in trackers:
            state = self.hass.states.get(entity_id)
            if state is None:
                observations.append(TrackerObservation(entity_id, "unavailable", None))
                continue
            connected_to = state.attributes.get("connected_to")
            observations.append(
                TrackerObservation(
                    entity_id,
                    state.state,
                    connected_to if isinstance(connected_to, str) else None,
                )
            )
        before = set(self.location.observed_access_points)
        remaining = self.location.observe(
            observations, now, int(self.options["location_debounce_seconds"])
        )
        if self.location.observed_access_points != before:
            self.history.location_data["observed_access_points"] = sorted(
                self.location.observed_access_points
            )
            self.history.schedule_save()
        if self._location_timer:
            self._location_timer()
            self._location_timer = None
        if remaining is not None:
            self._location_timer = async_call_later(
                self.hass, remaining + 0.1, self._location_refresh
            )
        return self.location.snapshot

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
                record = Usage(
                    now,
                    entity_id,
                    event.context.user_id,
                    source,
                    action,
                    confidence,
                    self.areas.get(entity_id),
                    presence,
                    context,
                    None,
                    self.location.snapshot.location_context,
                    self.location.snapshot.connected_to,
                )
                self.history.append(record)
                self.history.learning.resolve_exposure(
                    record, self._adaptive_settings(), now=dt_util.as_local(record.timestamp)
                )
                self.history.learning.record_action(
                    record,
                    self._adaptive_settings(),
                    local_timestamp=dt_util.as_local(record.timestamp),
                )
                self._request()

    async def _async_update_data(self) -> dict[str, Any]:
        if self._dirty:
            self._rebuild()
        now = dt_util.now()
        presence, context, active_areas = self._signal_snapshot()
        location = self._update_location(now)
        location_zone = self.location.zone(location.location_context)
        if location_zone and float(self.options["location_influence"]) > 0:
            active_areas = tuple(sorted(set(active_areas) | set(location_zone.area_ids)))
        active_location_entities = location_zone.entity_ids if location_zone else ()
        self.history.prune(now)
        adaptive_settings = self._adaptive_settings()
        self.history.learning.cleanup(now, adaptive_settings.retention_days, adaptive_settings)
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
            location_context=location.location_context,
            connected_to=location.connected_to,
            location_influence=float(self.options["location_influence"]),
            active_location_entity_ids=active_location_entities,
        )
        ai_used = False
        ai_cached = False
        ai_error = None
        base_ranks: dict[str, int] = {}
        adaptive_ranks: dict[str, int] = {}
        if self.options["presence_mode"] == "require_home" and presence is not True:
            ranked = []
            selected = []
        else:
            ranked = await self.hass.async_add_executor_job(
                rank, tuple(candidates.values()), tuple(self.history.records), now, settings
            )
            base_ranks = {item.entity_id: index for index, item in enumerate(ranked, 1)}
            ranked = await self.hass.async_add_executor_job(
                self.history.learning.apply_adaptive,
                ranked,
                now,
                adaptive_settings,
                self.options["user_id"] or None,
                presence,
                context_fingerprint(now, presence, context, location.location_context),
            )
            adaptive_ranks = {item.entity_id: index for index, item in enumerate(ranked, 1)}
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
                            "base_score": item.base_score,
                            "sequence_score": item.sequence_score,
                            "sequence_depth": item.sequence_depth,
                            "acceptance_rate": item.acceptance_rate,
                            "ignore_penalty": item.ignore_penalty,
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
                if privacy.context_entities and location.location_context:
                    context_rows.append(
                        {"id": "location_context", "state": location.location_context}
                    )
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
                    "base_score": item.score if item.pinned else item.base_score,
                    "sequence_score": item.sequence_score,
                    "sequence_depth": item.sequence_depth,
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
        if rows and self.options["adaptive_learning"]:
            self.history.learning.record_exposure(
                [row for row in rows if not row["pinned"]],
                now,
                adaptive_settings,
                context_hash=context_fingerprint(now, presence, context, location.location_context),
                source="unknown",
                confidence=0.35,
                user_id=self.options["user_id"] or None,
                base_ranks=base_ranks,
                adaptive_ranks=adaptive_ranks,
            )
            self.history.schedule_save()
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
            "location_context": location.location_context,
            "connected_to": location.connected_to,
            "location_source": location.source,
            "location_confidence": location.confidence,
            "location_tracker": location.tracker_entity_id,
            "last_connected_to": location.last_connected_to,
            "last_location_context": location.last_location_context,
            "location_last_changed": location.last_changed.isoformat()
            if location.last_changed
            else None,
            "location_pending_context": location.pending_context,
            "location_area_ids": list(location_zone.area_ids) if location_zone else [],
            "location_entity_ids": list(location_zone.entity_ids) if location_zone else [],
            "location_elapsed_seconds": round(
                max(0.0, (now - location.last_changed).total_seconds()), 1
            )
            if location.last_changed
            else None,
            "unassigned_access_points": list(self.location.unassigned_access_points),
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
                    "frequency_score": item.frequency,
                    "time": item.time,
                    "time_score": item.time,
                    "recency": item.recency,
                    "recency_score": item.recency,
                    "confidence": item.confidence,
                    "current_state": item.current_state,
                    "weekday": item.weekday,
                    "weekday_score": item.weekday,
                    "presence": item.presence,
                    "area": item.area,
                    "context": item.context,
                    "context_score": item.context,
                    "location": item.location,
                    "location_score": item.location,
                    "base": item.base_score,
                    "base_score": item.base_score,
                    "sequence": item.sequence_score,
                    "sequence_score": item.sequence_score,
                    "sequence_depth": item.sequence_depth,
                    "acceptance": item.acceptance_score,
                    "acceptance_score": item.acceptance_score,
                    "acceptance_rate": item.acceptance_rate,
                    "ignored": item.ignore_penalty,
                    "ignore_penalty": item.ignore_penalty,
                    "adaptive_confidence": item.adaptive_confidence,
                    "final": item.score,
                    "final_score": item.score,
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

    def learning_stats(
        self, entity_id: str | None = None, user_id: str | None = None
    ) -> dict[str, Any]:
        """Return aggregate diagnostics for an explicitly requested profile/entity."""
        records = [
            row
            for row in self.history.records
            if (entity_id is None or row.entity_id == entity_id)
            and (user_id is None or row.user_id == user_id)
        ]
        if entity_id is None:
            return {
                "actions": len(records),
                "sequence_patterns": len(self.history.learning.transitions),
                "sequence_chain_patterns": len(self.history.learning.chains),
                **self.history.learning.metrics_snapshot(),
            }
        return {
            "entity_id": entity_id,
            "actions": len(records),
            **self.history.learning.entity_feedback_stats(entity_id, user_id=user_id),
            "top_predecessors": self.history.learning.top_predecessors(entity_id, user_id=user_id),
            "top_sequences": self.history.learning.top_chains(entity_id, user_id=user_id),
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
                record = Usage(
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
                    self.location.snapshot.location_context,
                    self.location.snapshot.connected_to,
                )
                local_now = dt_util.as_local(record.timestamp)
                self.history.learning.record_exposure(
                    [
                        {
                            "entity_id": entity_id,
                            "rank": slot,
                            "slot": slot,
                            "score": result.get("score", 0),
                        }
                    ],
                    local_now,
                    self._adaptive_settings(),
                    context_hash=context_fingerprint(
                        local_now,
                        presence,
                        context_states,
                        self.location.snapshot.location_context,
                    ),
                    source=source if source in QUICK_ACCESS_SOURCES else "unknown",
                    confidence=1.0,
                    user_id=context.user_id,
                    force=True,
                )
                self.history.append(record)
                self.history.learning.resolve_exposure(
                    record, self._adaptive_settings(), now=local_now
                )
                self.history.learning.record_action(
                    record,
                    self._adaptive_settings(),
                    local_timestamp=dt_util.as_local(record.timestamp),
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

    async def async_execute_terminal_entity(
        self, entity_id: str, slot: int, context: Context
    ) -> dict[str, Any]:
        """Execute an entity from a terminal-owned stable slot using existing safety/learning."""
        async with self._quick_access_lock:
            if not self._quick_target_valid(entity_id):
                return {"entity_id": entity_id, "success": False, "reason": "unavailable_target"}
            rejection = safety_rejection(
                entity_id,
                self.options["quick_access_safety_mode"],
                self.options["quick_access_sensitive_entities"],
                False,
            )
            if rejection:
                self.sensitive_action_rejections += 1
                return {
                    "entity_id": entity_id,
                    "success": False,
                    "reason": rejection,
                    "requires_confirmation": True,
                }
            state = self.hass.states.get(entity_id)
            assert state is not None
            supported = int(state.attributes.get("supported_features", 0) or 0)
            media_mask = int(MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PAUSE)
            action = resolve_default_action(entity_id, state.state, supported, media_mask)
            if action is None or not self.hass.services.has_service(action.domain, action.service):
                return {"entity_id": entity_id, "success": False, "reason": "unsupported_action"}
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
                    return {"entity_id": entity_id, "success": False, "reason": "service_error"}
            finally:
                self._quick_access_contexts.discard(context.id)
            await self._async_track_terminal_usage(entity_id, action.name, slot, context)
            self.quick_access_executions += 1
            return {"entity_id": entity_id, "action": action.name, "success": True}

    async def async_adjust_terminal_slot(
        self, entity_id: str, delta: int, context: Context
    ) -> dict[str, Any]:
        """Adjust only explicit number, climate or media controls from terminal mode."""
        if not delta or not self._quick_target_valid(entity_id):
            return {"entity_id": entity_id, "success": False, "reason": "unavailable_target"}
        state = self.hass.states.get(entity_id)
        assert state is not None
        domain = entity_id.partition(".")[0]
        data: dict[str, Any]
        if domain == "number":
            try:
                value = float(state.state) + delta * float(state.attributes.get("step", 1))
            except TypeError, ValueError:
                return {"entity_id": entity_id, "success": False, "reason": "invalid_value"}
            value = max(
                float(state.attributes.get("min", value)),
                min(value, float(state.attributes.get("max", value))),
            )
            action_domain, action_name, data = "number", "set_value", {"value": value}
        elif domain == "climate":
            current = state.attributes.get("temperature")
            if not isinstance(current, (int, float)):
                return {"entity_id": entity_id, "success": False, "reason": "unsupported_action"}
            value = float(current) + delta * float(state.attributes.get("target_temp_step", 0.5))
            value = max(
                float(state.attributes.get("min_temp", value)),
                min(value, float(state.attributes.get("max_temp", value))),
            )
            action_domain, action_name, data = "climate", "set_temperature", {"temperature": value}
        elif domain == "media_player":
            current = state.attributes.get("volume_level")
            if not isinstance(current, (int, float)):
                return {"entity_id": entity_id, "success": False, "reason": "unsupported_action"}
            value = max(0.0, min(1.0, float(current) + delta * 0.05))
            action_domain, action_name, data = "media_player", "volume_set", {"volume_level": value}
        elif domain == "light":
            current = state.attributes.get("brightness")
            if not isinstance(current, (int, float)):
                current = 128 if state.state != "off" else 0
            value = max(0, min(255, round(float(current) + delta * 13)))
            if value == 0:
                action_domain, action_name, data = "light", "turn_off", {}
            else:
                action_domain, action_name, data = "light", "turn_on", {"brightness": value}
        else:
            return {"entity_id": entity_id, "success": False, "reason": "unsupported_action"}
        if not self.hass.services.has_service(action_domain, action_name):
            return {"entity_id": entity_id, "success": False, "reason": "unsupported_action"}
        await self.hass.services.async_call(
            action_domain,
            action_name,
            {"entity_id": entity_id, **data},
            blocking=True,
            context=context,
        )
        return {"entity_id": entity_id, "action": action_name, "value": value, "success": True}

    async def _async_track_terminal_usage(
        self, entity_id: str, action_name: str, slot: int, context: Context
    ) -> None:
        if not self.options["quick_access_track_usage"]:
            return
        now = dt_util.utcnow()
        presence, context_states, _active_areas = self._signal_snapshot()
        record = Usage(
            now,
            entity_id,
            context.user_id,
            "quick_access",
            action_name,
            float(self.options["quick_access_usage_weight"]) / 100,
            self.areas.get(entity_id),
            presence,
            context_states,
            "context_dial",
            self.location.snapshot.location_context,
            self.location.snapshot.connected_to,
        )
        local_now = dt_util.as_local(record.timestamp)
        self.history.learning.record_exposure(
            [{"entity_id": entity_id, "rank": slot, "slot": slot}],
            local_now,
            self._adaptive_settings(),
            context_hash=context_fingerprint(
                local_now, presence, context_states, self.location.snapshot.location_context
            ),
            source="context_dial",
            confidence=1.0,
            user_id=context.user_id,
            force=True,
        )
        self.history.append(record)
        self.history.learning.resolve_exposure(record, self._adaptive_settings(), now=local_now)
        self.history.learning.record_action(
            record, self._adaptive_settings(), local_timestamp=local_now
        )
        self._request()

    async def async_close(self) -> None:
        self._closed = True
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._pending_refresh:
            self._pending_refresh()
            self._pending_refresh = None
        if self._location_timer:
            self._location_timer()
            self._location_timer = None
        await self.async_shutdown()
        await self.history.async_flush()
