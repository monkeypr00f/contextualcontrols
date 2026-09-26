"""Two-screen onboarding and sectioned native-selector options."""

from copy import deepcopy

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    AI_PROVIDERS,
    DEFAULTS,
    DOMAIN,
    LEARNING_SOURCES,
    MODES,
    NAME,
    PRESENCE_DOMAINS,
    QUICK_ACCESS_SAFETY_MODES,
    QUICK_ACCESS_STABILITY,
    SUPPORTED_DOMAINS,
)

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
    "advanced": ("minimum_confidence", "cold_start", "debug"),
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
}
NUMERIC_CHOICES = {"learning_period_days", "time_window_minutes", "refresh_minutes"}
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
        )
        else value
        for key, value in values.items()
    }


class ContextualConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 3

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
    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=[*SECTIONS, "ai", "reset"])

    async def _section(self, section, user_input):
        options = {**deepcopy(DEFAULTS), **self.config_entry.options}
        if user_input is not None:
            options.update(normalize(user_input))
            if section == "learning" and options["user_id"]:
                user = await self.hass.auth.async_get_user(options["user_id"])
                if user is None:
                    return self.async_show_form(
                        step_id=section,
                        data_schema=schema_for(SECTIONS[section], options),
                        errors={"user_id": "unknown_user"},
                    )
            if (
                section == "context"
                and options["presence_mode"] == "require_home"
                and not options["presence_entities"]
            ):
                return self.async_show_form(
                    step_id=section,
                    data_schema=schema_for(SECTIONS[section], options),
                    errors={"presence_entities": "presence_required"},
                )
            return self.async_create_entry(title="", data=options)
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

    async def async_step_dashboard(self, user_input=None):
        return await self._section("dashboard", user_input)

    async def async_step_quick_access(self, user_input=None):
        return await self._section("quick_access", user_input)

    async def async_step_advanced(self, user_input=None):
        return await self._section("advanced", user_input)

    async def async_step_ai(self, user_input=None):
        options = {**deepcopy(DEFAULTS), **self.config_entry.options}
        if user_input is None:
            return self.async_show_form(
                step_id="ai", data_schema=schema_for(AI_COMMON_FIELDS, options)
            )
        options.update(normalize(user_input))
        provider = options["ai_provider"]
        if provider == "disabled":
            return self.async_create_entry(title="", data=options)
        self._pending_ai_options = options
        return await getattr(self, f"async_step_ai_{provider}")()

    async def async_step_ai_ollama(self, user_input=None):
        options = self._pending_ai_options
        if user_input is not None:
            options.update(normalize(user_input))
            return self.async_create_entry(title="", data=options)
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
                data = {**self.config_entry.data, "openai_api_key": api_key}
                self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            if not self.config_entry.data.get("openai_api_key") and not api_key:
                return self.async_show_form(
                    step_id="ai_openai_compatible",
                    data_schema=self._openai_schema(options),
                    errors={"api_key": "api_key_required"},
                )
            return self.async_create_entry(title="", data=options)
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
            elif not getattr(self.config_entry, "runtime_data", None):
                errors["base"] = "entry_not_loaded"
            else:
                coordinator = self.config_entry.runtime_data
                await coordinator.history.async_reset(
                    user_input.get("entity_id"), user_input.get("user_id") or None
                )
                await coordinator.async_refresh()
                return self.async_create_entry(title="", data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="reset",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Optional("entity_id"): selector.EntitySelector(),
                    vol.Optional("user_id"): selector.TextSelector(),
                    vol.Required("confirm", default=False): selector.BooleanSelector(),
                }
            ),
        )
