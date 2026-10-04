"""Two-screen onboarding and sectioned native-selector options."""

import re
from copy import deepcopy

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import selector

from .const import (
    AI_PROVIDERS,
    DEFAULTS,
    DOMAIN,
    LEARNING_SCOPES,
    LEARNING_SOURCES,
    MODES,
    NAME,
    PRESENCE_DOMAINS,
    QUICK_ACCESS_SAFETY_MODES,
    QUICK_ACCESS_STABILITY,
    SUPPORTED_DOMAINS,
)
from .location import normalize_zones, zones_to_options

LOCATION_ID = re.compile(r"^[a-z0-9_]+$")

SECTIONS = {
    "general": ("mode", "suggestion_count", "refresh_minutes"),
    "entities": (
        "included_entities",
        "included_domains",
        "excluded_entities",
        "excluded_domains",
        "all_areas",
        "included_areas",
        "excluded_areas",
    ),
    "learning": (
        "learning_period_days",
        "time_window_minutes",
        "recency_weight",
        "learn_sources",
        "user_id",
        "ignored_entities",
        "consider_weekday",
        "weekday_mode",
    ),
    "context": ("presence_entities", "presence_mode", "context_entities"),
    "dashboard": ("pinned_entities", "pinned_position", "pinned_use_slots"),
    "quick_access": (
        "quick_access_enabled",
        "quick_access_slots",
        "quick_access_safety_mode",
        "quick_access_stability",
        "quick_access_sensitive_entities",
        "quick_access_response",
        "quick_access_track_usage",
        "quick_access_usage_weight",
    ),
    "terminals": (),
    "advanced": ("minimum_confidence", "cold_start", "debug"),
    "adaptive": (
        "adaptive_learning",
        "sequence_learning",
        "sequence_window_minutes",
        "sequence_influence",
        "minimum_transition_occurrences",
        "sequence_decay_days",
        "ignored_suggestion_learning",
        "suggestion_acceptance_window_minutes",
        "minimum_exposures",
        "ignored_suggestion_penalty",
        "acceptance_boost",
        "prediction_influence",
        "learning_scope",
        "adaptive_retention_days",
    ),
    "adaptive_sources": (
        "adaptive_weight_manual",
        "adaptive_weight_assist",
        "adaptive_weight_quick_access",
        "adaptive_weight_apple_watch",
        "adaptive_weight_shortcut",
        "adaptive_weight_script",
        "adaptive_weight_automation",
        "adaptive_weight_unknown",
    ),
}
AI_COMMON_FIELDS = (
    "ai_provider",
    "candidate_pool_size",
    "ai_min_refresh_minutes",
    "ai_share_entity_id",
    "ai_share_friendly_name",
    "ai_share_current_state",
    "ai_share_area",
    "ai_share_usage_statistics",
    "ai_share_exact_timestamps",
    "ai_share_presence_information",
    "ai_share_context_entities",
)
AI_PROVIDER_FIELDS = {
    "ollama": ("ollama_url", "ollama_model", "ai_timeout_seconds", "ai_temperature"),
    "openai_compatible": (
        "openai_endpoint",
        "openai_model",
        "ai_timeout_seconds",
        "ai_temperature",
    ),
}
CHOICES = {
    "mode": MODES,
    "ai_provider": AI_PROVIDERS,
    "included_domains": SUPPORTED_DOMAINS,
    "excluded_domains": SUPPORTED_DOMAINS,
    "learning_period_days": ["7", "14", "21", "30", "60", "90"],
    "time_window_minutes": ["30", "60", "90", "120", "180"],
    "learn_sources": LEARNING_SOURCES,
    "weekday_mode": ["exact", "workweek", "none"],
    "presence_mode": ["ignore", "signal", "require_home"],
    "refresh_minutes": ["0", "5", "10", "15", "30", "60"],
    "pinned_position": ["before", "after"],
    "cold_start": ["pinned", "recent", "frequent", "domains"],
    "quick_access_safety_mode": QUICK_ACCESS_SAFETY_MODES,
    "quick_access_stability": QUICK_ACCESS_STABILITY,
    "sequence_window_minutes": ["5", "10", "15", "30", "60", "120"],
    "sequence_decay_days": ["7", "14", "30", "60", "90"],
    "suggestion_acceptance_window_minutes": ["2", "5", "10", "15", "30"],
    "learning_scope": LEARNING_SCOPES,
    "adaptive_retention_days": ["30", "60", "90", "180", "365"],
    "reset_mode": ["all", "historical", "sequence", "feedback", "user", "entity"],
}
NUMERIC_CHOICES = {
    "learning_period_days",
    "time_window_minutes",
    "refresh_minutes",
    "sequence_window_minutes",
    "sequence_decay_days",
    "suggestion_acceptance_window_minutes",
    "adaptive_retention_days",
}
MULTIPLE_CHOICES = {"included_domains", "excluded_domains", "learn_sources"}
ENTITY_FIELDS = {
    "included_entities",
    "excluded_entities",
    "pinned_entities",
    "ignored_entities",
    "context_entities",
    "quick_access_sensitive_entities",
}
PRESENCE_FIELDS = {"presence_entities"}
LOCATION_TRACKER_FIELDS = {"location_trackers"}
AREA_FIELDS = {"included_areas", "excluded_areas"}
BOOLEAN_FIELDS = {
    "all_areas",
    "pinned_use_slots",
    "consider_weekday",
    "debug",
    "ai_share_entity_id",
    "ai_share_friendly_name",
    "ai_share_current_state",
    "ai_share_area",
    "ai_share_usage_statistics",
    "ai_share_exact_timestamps",
    "ai_share_presence_information",
    "ai_share_context_entities",
    "quick_access_enabled",
    "quick_access_response",
    "quick_access_track_usage",
    "adaptive_learning",
    "sequence_learning",
    "ignored_suggestion_learning",
}
TEXT_FIELDS = {"ollama_url", "ollama_model", "openai_endpoint", "openai_model", "user_id"}
NUMBER_RANGES = {
    "suggestion_count": (1, 12, 1),
    "minimum_confidence": (0, 100, 1),
    "recency_weight": (0, 100, 1),
    "candidate_pool_size": (6, 30, 1),
    "ai_min_refresh_minutes": (5, 120, 1),
    "ai_timeout_seconds": (1, 120, 1),
    "ai_temperature": (0, 1, 0.1),
    "quick_access_slots": (1, 10, 1),
    "quick_access_usage_weight": (0, 100, 1),
    "sequence_influence": (0, 100, 1),
    "minimum_transition_occurrences": (2, 10, 1),
    "minimum_exposures": (3, 20, 1),
    "ignored_suggestion_penalty": (0, 100, 1),
    "acceptance_boost": (0, 100, 1),
    "prediction_influence": (0, 100, 1),
    "adaptive_weight_manual": (0, 100, 1),
    "adaptive_weight_assist": (0, 100, 1),
    "adaptive_weight_quick_access": (0, 100, 1),
    "adaptive_weight_apple_watch": (0, 100, 1),
    "adaptive_weight_shortcut": (0, 100, 1),
    "adaptive_weight_script": (0, 100, 1),
    "adaptive_weight_automation": (0, 100, 1),
    "adaptive_weight_unknown": (0, 100, 1),
    "location_debounce_seconds": (0, 120, 1),
    "location_influence": (0, 100, 1),
}


def schema_for(keys, options):
    fields = {}
    for key in keys:
        value = options[key]
        if key in PRESENCE_FIELDS:
            control = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    multiple=True,
                    filter={"domain": PRESENCE_DOMAINS},
                )
            )
        elif key in LOCATION_TRACKER_FIELDS:
            control = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    multiple=True,
                    filter={"domain": "device_tracker"},
                )
            )
        elif key in ENTITY_FIELDS:
            entity_config = {"multiple": True, "reorder": key == "pinned_entities"}
            if key != "context_entities":
                entity_config["filter"] = {"domain": SUPPORTED_DOMAINS}
            control = selector.EntitySelector(selector.EntitySelectorConfig(**entity_config))
        elif key in AREA_FIELDS:
            control = selector.AreaSelector(selector.AreaSelectorConfig(multiple=True))
        elif key in BOOLEAN_FIELDS:
            control = selector.BooleanSelector()
        elif key in CHOICES:
            control = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=CHOICES[key],
                    multiple=key in MULTIPLE_CHOICES,
                    translation_key=key,
                    mode=selector.SelectSelectorMode.LIST
                    if key in MULTIPLE_CHOICES
                    else selector.SelectSelectorMode.DROPDOWN,
                )
            )
            if key in NUMERIC_CHOICES:
                value = str(value)
        elif key in TEXT_FIELDS:
            control = selector.TextSelector()
        else:
            minimum, maximum, step = NUMBER_RANGES[key]
            control = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=minimum,
                    max=maximum,
                    step=step,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            )
        marker = vol.Optional if key == "user_id" else vol.Required
        fields[marker(key, default=deepcopy(value))] = control
    return vol.Schema(fields)


def terminal_schema(mappings: dict[str, str]) -> vol.Schema:
    """Use native selectors instead of exposing the stored mapping syntax."""
    fields: dict = {
        vol.Optional("terminal_id"): selector.TextSelector(),
        vol.Optional("terminal_area"): selector.AreaSelector(),
    }
    if mappings:
        fields[vol.Optional("remove_terminal")] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=sorted(mappings), mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
    return vol.Schema(fields)


def serialize_terminal_mappings(mappings: dict[str, str]) -> str:
    """Persist mappings in the backward-compatible compact options format."""
    return ",".join(f"{terminal}:{area}" for terminal, area in sorted(mappings.items()))


def normalize(values):
    return {
        key: int(value)
        if key in NUMERIC_CHOICES
        or key
        in (
            "suggestion_count",
            "minimum_confidence",
            "recency_weight",
            "candidate_pool_size",
            "ai_min_refresh_minutes",
            "ai_timeout_seconds",
            "quick_access_slots",
            "quick_access_usage_weight",
            "sequence_influence",
            "minimum_transition_occurrences",
            "minimum_exposures",
            "ignored_suggestion_penalty",
            "acceptance_boost",
            "prediction_influence",
            "adaptive_weight_manual",
            "adaptive_weight_assist",
            "adaptive_weight_quick_access",
            "adaptive_weight_apple_watch",
            "adaptive_weight_shortcut",
            "adaptive_weight_script",
            "adaptive_weight_automation",
            "adaptive_weight_unknown",
            "location_debounce_seconds",
            "location_influence",
        )
        else value
        for key, value in values.items()
    }


class ContextualConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 5

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._name = user_input["name"].strip() or NAME
            self._mode = user_input["mode"]
            return await self.async_step_entities()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=NAME): selector.TextSelector(),
                    vol.Required("mode", default=DEFAULTS["mode"]): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=MODES, translation_key="mode")
                    ),
                }
            ),
        )

    async def async_step_entities(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={},
                options={
                    **deepcopy(DEFAULTS),
                    "mode": self._mode,
                    **normalize(user_input),
                },
            )
        return self.async_show_form(
            step_id="entities",
            data_schema=schema_for(
                ("included_entities", "included_domains", "excluded_entities"), DEFAULTS
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ContextualOptionsFlow()


class ContextualOptionsFlow(OptionsFlowWithReload):
    def _ensure_draft(self) -> None:
        """Create a flow-local draft so users can edit several sections."""
        if not hasattr(self, "_draft_options"):
            self._draft_options = {
                **deepcopy(DEFAULTS),
                **deepcopy(dict(self.config_entry.options)),
            }
            self._draft_entry_data = deepcopy(dict(self.config_entry.data))

    async def async_step_init(self, user_input=None):
        self._ensure_draft()
        menu = list(SECTIONS)
        menu.insert(menu.index("dashboard"), "location")
        return self.async_show_menu(step_id="init", menu_options=[*menu, "ai", "reset", "save"])

    async def _section(self, section, user_input):
        self._ensure_draft()
        options = self._draft_options
        if user_input is not None:
            proposed = {**options, **normalize(user_input)}
            if section == "learning" and proposed["user_id"]:
                user = await self.hass.auth.async_get_user(proposed["user_id"])
                if user is None:
                    return self.async_show_form(
                        step_id=section,
                        data_schema=schema_for(SECTIONS[section], proposed),
                        errors={"user_id": "unknown_user"},
                    )
            if (
                section == "context"
                and proposed["presence_mode"] == "require_home"
                and not proposed["presence_entities"]
            ):
                return self.async_show_form(
                    step_id=section,
                    data_schema=schema_for(SECTIONS[section], proposed),
                    errors={"presence_entities": "presence_required"},
                )
            if section == "terminals":
                from .terminal import parse_terminal_mappings

                try:
                    parse_terminal_mappings(proposed["terminal_mappings"])
                except ValueError:
                    return self.async_show_form(
                        step_id=section,
                        data_schema=schema_for(SECTIONS[section], proposed),
                        errors={"terminal_mappings": "invalid_terminal_mappings"},
                    )
            self._draft_options = proposed
            return await self.async_step_init()
        return self.async_show_form(
            step_id=section, data_schema=schema_for(SECTIONS[section], options)
        )

    async def async_step_general(self, user_input=None):
        return await self._section("general", user_input)

    async def async_step_entities(self, user_input=None):
        return await self._section("entities", user_input)

    async def async_step_learning(self, user_input=None):
        return await self._section("learning", user_input)

    async def async_step_context(self, user_input=None):
        return await self._section("context", user_input)

    async def async_step_terminals(self, user_input=None):
        self._ensure_draft()
        from .terminal import parse_terminal_mappings

        options = self._draft_options
        mappings = parse_terminal_mappings(options["terminal_mappings"])
        if user_input is not None:
            terminal_id = str(user_input.get("terminal_id", "")).strip()
            area_id = user_input.get("terminal_area")
            remove_terminal = user_input.get("remove_terminal")
            errors = {}
            if terminal_id or area_id:
                if not terminal_id:
                    errors["terminal_id"] = "terminal_id_required"
                elif not area_id:
                    errors["terminal_area"] = "terminal_area_required"
                elif not terminal_id.replace("_", "").isalnum():
                    errors["terminal_id"] = "invalid_terminal_id"
                else:
                    mappings[terminal_id] = area_id
            if remove_terminal:
                mappings.pop(remove_terminal, None)
            if errors:
                return self.async_show_form(
                    step_id="terminals",
                    data_schema=terminal_schema(mappings),
                    errors=errors,
                    description_placeholders={
                        "configured_terminals": self._terminal_summary(mappings)
                    },
                )
            self._draft_options = {
                **options,
                "terminal_mappings": serialize_terminal_mappings(mappings),
            }
            return await self.async_step_init()

        return self.async_show_form(
            step_id="terminals",
            data_schema=terminal_schema(mappings),
            description_placeholders={"configured_terminals": self._terminal_summary(mappings)},
        )

    def _terminal_summary(self, mappings: dict[str, str]) -> str:
        """Provide a friendly summary while the option flow remains open."""
        if not mappings:
            return "Nessun terminale configurato."
        areas = ar.async_get(self.hass)
        summary = []
        for terminal, area_id in sorted(mappings.items()):
            area = areas.async_get_area(area_id)
            summary.append(f"{terminal} → {area.name if area else area_id}")
        return ", ".join(summary)

    def _location_zones(self):
        self._ensure_draft()
        return zones_to_options(normalize_zones(self._draft_options["location_contexts"]))

    def _observed_access_points(self):
        self._ensure_draft()
        observed = set()
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is not None:
            observed.update(runtime.location.observed_access_points)
        for entity_id in self._draft_options["location_trackers"]:
            state = self.hass.states.get(entity_id)
            if state and isinstance(state.attributes.get("connected_to"), str):
                value = state.attributes["connected_to"].strip()
                if value:
                    observed.add(value)
        return sorted(observed, key=str.casefold)

    async def async_step_location(self, user_input=None):
        """Open the Location Context editor without discarding the draft."""
        self._ensure_draft()
        menu = ["location_settings", "location_add"]
        if self._location_zones():
            menu.extend(("location_edit", "location_delete"))
        menu.extend(("location_unassigned", "location_back"))
        return self.async_show_menu(step_id="location", menu_options=menu)

    async def async_step_location_back(self, user_input=None):
        return await self.async_step_init()

    async def async_step_location_settings(self, user_input=None):
        self._ensure_draft()
        keys = ("location_trackers", "location_debounce_seconds", "location_influence")
        if user_input is not None:
            self._draft_options.update(normalize(user_input))
            return await self.async_step_location()
        return self.async_show_form(
            step_id="location_settings",
            data_schema=schema_for(keys, self._draft_options),
        )

    def _zone_selector(self, default=None):
        zones = self._location_zones()
        return vol.Schema(
            {
                vol.Required(
                    "location_zone_id", default=default or zones[0]["id"]
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[zone["id"] for zone in zones],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    async def async_step_location_add(self, user_input=None):
        self._editing_location_id = None
        return await self.async_step_location_zone(user_input)

    async def async_step_location_edit(self, user_input=None):
        if user_input is not None:
            self._editing_location_id = user_input["location_zone_id"]
            return await self.async_step_location_zone()
        return self.async_show_form(step_id="location_edit", data_schema=self._zone_selector())

    def _location_zone_schema(self, current, editing=False):
        access_points = sorted(
            set(self._observed_access_points()) | set(current.get("access_points", [])),
            key=str.casefold,
        )
        fields = {}
        if not editing:
            fields[vol.Required("location_zone_id", default=current.get("id", ""))] = (
                selector.TextSelector()
            )
        fields.update(
            {
                vol.Required(
                    "location_zone_name", default=current.get("name", "")
                ): selector.TextSelector(),
                vol.Required(
                    "location_access_points", default=current.get("access_points", [])
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=access_points,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    "location_areas", default=current.get("areas", [])
                ): selector.AreaSelector(selector.AreaSelectorConfig(multiple=True)),
                vol.Optional(
                    "location_entities", default=current.get("entities", [])
                ): selector.EntitySelector(selector.EntitySelectorConfig(multiple=True)),
            }
        )
        return vol.Schema(fields)

    async def async_step_location_zone(self, user_input=None):
        self._ensure_draft()
        zones = self._location_zones()
        editing_id = getattr(self, "_editing_location_id", None)
        current = next((zone for zone in zones if zone["id"] == editing_id), {})
        errors = {}
        if user_input is not None:
            context_id = editing_id or user_input["location_zone_id"].strip().lower().replace(
                "-", "_"
            )
            if not LOCATION_ID.fullmatch(context_id):
                errors["location_zone_id"] = "invalid_location_id"
            elif any(zone["id"] == context_id and zone["id"] != editing_id for zone in zones):
                errors["location_zone_id"] = "duplicate_location_id"
            elif not user_input["location_zone_name"].strip():
                errors["location_zone_name"] = "location_name_required"
            else:
                assigned = set(user_input["location_access_points"])
                updated = []
                for zone in zones:
                    if zone["id"] == editing_id:
                        continue
                    updated.append(
                        {
                            **zone,
                            "access_points": [
                                value for value in zone["access_points"] if value not in assigned
                            ],
                        }
                    )
                updated.append(
                    {
                        "id": context_id,
                        "name": user_input["location_zone_name"].strip(),
                        "access_points": list(user_input["location_access_points"]),
                        "areas": list(user_input.get("location_areas", [])),
                        "entities": list(user_input.get("location_entities", [])),
                    }
                )
                self._draft_options["location_contexts"] = zones_to_options(
                    normalize_zones(updated)
                )
                return await self.async_step_location()
        return self.async_show_form(
            step_id="location_zone",
            data_schema=self._location_zone_schema(
                current
                if user_input is None
                else {
                    "id": user_input.get("location_zone_id", ""),
                    "name": user_input.get("location_zone_name", ""),
                    "access_points": user_input.get("location_access_points", []),
                    "areas": user_input.get("location_areas", []),
                    "entities": user_input.get("location_entities", []),
                },
                editing=editing_id is not None,
            ),
            errors=errors,
        )

    async def async_step_location_delete(self, user_input=None):
        self._ensure_draft()
        errors = {}
        if user_input is not None:
            if not user_input.get("confirm"):
                errors["confirm"] = "confirmation_required"
            else:
                context_id = user_input["location_zone_id"]
                self._draft_options["location_contexts"] = [
                    zone for zone in self._location_zones() if zone["id"] != context_id
                ]
                return await self.async_step_location()
        fields = dict(self._zone_selector().schema)
        fields[vol.Required("confirm", default=False)] = selector.BooleanSelector()
        return self.async_show_form(
            step_id="location_delete", data_schema=vol.Schema(fields), errors=errors
        )

    async def async_step_location_unassigned(self, user_input=None):
        if user_input is not None:
            return await self.async_step_location()
        assigned = {value for zone in self._location_zones() for value in zone["access_points"]}
        unassigned = [value for value in self._observed_access_points() if value not in assigned]
        return self.async_show_form(
            step_id="location_unassigned",
            data_schema=vol.Schema({}),
            description_placeholders={
                "access_points": ", ".join(unassigned) if unassigned else "—"
            },
        )

    async def async_step_dashboard(self, user_input=None):
        return await self._section("dashboard", user_input)

    async def async_step_quick_access(self, user_input=None):
        return await self._section("quick_access", user_input)

    async def async_step_advanced(self, user_input=None):
        return await self._section("advanced", user_input)

    async def async_step_adaptive(self, user_input=None):
        return await self._section("adaptive", user_input)

    async def async_step_adaptive_sources(self, user_input=None):
        return await self._section("adaptive_sources", user_input)

    async def async_step_ai(self, user_input=None):
        self._ensure_draft()
        options = self._draft_options
        if user_input is None:
            return self.async_show_form(
                step_id="ai", data_schema=schema_for(AI_COMMON_FIELDS, options)
            )
        proposed = {**options, **normalize(user_input)}
        provider = proposed["ai_provider"]
        if provider == "disabled":
            self._draft_options = proposed
            return await self.async_step_init()
        self._pending_ai_options = proposed
        return await getattr(self, f"async_step_ai_{provider}")()

    async def async_step_ai_ollama(self, user_input=None):
        options = self._pending_ai_options
        if user_input is not None:
            options.update(normalize(user_input))
            self._draft_options = options
            return await self.async_step_init()
        return self.async_show_form(
            step_id="ai_ollama",
            data_schema=schema_for(AI_PROVIDER_FIELDS["ollama"], options),
        )

    async def async_step_ai_openai_compatible(self, user_input=None):
        options = self._pending_ai_options
        if user_input is not None:
            api_key = user_input.pop("api_key", "").strip()
            options.update(normalize(user_input))
            if api_key:
                self._draft_entry_data["openai_api_key"] = api_key
            if not self._draft_entry_data.get("openai_api_key"):
                return self.async_show_form(
                    step_id="ai_openai_compatible",
                    data_schema=self._openai_schema(options),
                    errors={"api_key": "api_key_required"},
                )
            self._draft_options = options
            return await self.async_step_init()
        return self.async_show_form(
            step_id="ai_openai_compatible", data_schema=self._openai_schema(options)
        )

    @staticmethod
    def _openai_schema(options):
        fields = dict(schema_for(AI_PROVIDER_FIELDS["openai_compatible"], options).schema)
        fields[vol.Optional("api_key")] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        return vol.Schema(fields)

    async def async_step_reset(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not user_input.get("confirm"):
                errors["confirm"] = "confirmation_required"
            elif user_input["reset_mode"] == "user" and not user_input.get("user_id"):
                errors["user_id"] = "user_required"
            elif user_input["reset_mode"] == "entity" and not user_input.get("entity_id"):
                errors["entity_id"] = "entity_required"
            elif not getattr(self.config_entry, "runtime_data", None):
                errors["base"] = "entry_not_loaded"
            else:
                coordinator = self.config_entry.runtime_data
                await coordinator.history.async_reset_mode(
                    user_input["reset_mode"],
                    user_input.get("entity_id"),
                    user_input.get("user_id") or None,
                )
                await coordinator.async_refresh()
                return await self.async_step_init()
        return self.async_show_form(
            step_id="reset",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("reset_mode", default="all"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=CHOICES["reset_mode"], translation_key="reset_mode"
                        )
                    ),
                    vol.Optional("entity_id"): selector.EntitySelector(),
                    vol.Optional("user_id"): selector.TextSelector(),
                    vol.Required("confirm", default=False): selector.BooleanSelector(),
                }
            ),
        )

    async def async_step_save(self, user_input=None):
        """Persist the whole draft and let OptionsFlowWithReload reload once."""
        self._ensure_draft()
        if self._draft_entry_data != dict(self.config_entry.data):
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=self._draft_entry_data
            )
        return self.async_create_entry(title="", data=self._draft_options)
