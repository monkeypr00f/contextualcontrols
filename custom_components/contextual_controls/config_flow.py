"""Two-screen onboarding and sectioned native-selector options."""

from copy import deepcopy

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DEFAULTS, DOMAIN, NAME, SUPPORTED_DOMAINS

SECTIONS = {
    "general": ("suggestion_count", "refresh_minutes"),
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
    ),
    "dashboard": ("pinned_entities", "pinned_position", "pinned_use_slots"),
    "advanced": ("minimum_confidence", "cold_start", "debug"),
}
CHOICES = {
    "included_domains": SUPPORTED_DOMAINS,
    "excluded_domains": SUPPORTED_DOMAINS,
    "learning_period_days": ["7", "14", "21", "30", "60", "90"],
    "time_window_minutes": ["30", "60", "90", "120", "180"],
    "learn_sources": ["user", "child", "unknown"],
    "refresh_minutes": ["0", "5", "10", "15", "30", "60"],
    "pinned_position": ["before", "after"],
    "cold_start": ["pinned", "recent", "frequent", "domains"],
}
NUMERIC_CHOICES = {"learning_period_days", "time_window_minutes", "refresh_minutes"}
MULTIPLE_CHOICES = {"included_domains", "excluded_domains", "learn_sources"}
ENTITY_FIELDS = {"included_entities", "excluded_entities", "pinned_entities", "ignored_entities"}
AREA_FIELDS = {"included_areas", "excluded_areas"}
BOOLEAN_FIELDS = {"all_areas", "pinned_use_slots", "debug"}


def schema_for(keys, options):
    fields = {}
    for key in keys:
        value = options[key]
        if key in ENTITY_FIELDS:
            control = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    multiple=True,
                    reorder=key == "pinned_entities",
                    filter={"domain": SUPPORTED_DOMAINS},
                )
            )
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
        elif key == "user_id":
            control = selector.TextSelector()
        else:
            minimum, maximum = (1, 12) if key == "suggestion_count" else (0, 100)
            control = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=minimum, max=maximum, step=1, mode=selector.NumberSelectorMode.SLIDER
                )
            )
        marker = vol.Optional if key == "user_id" else vol.Required
        fields[marker(key, default=deepcopy(value))] = control
    return vol.Schema(fields)


def normalize(values):
    return {
        key: int(value)
        if key in NUMERIC_CHOICES
        or key in ("suggestion_count", "minimum_confidence", "recency_weight")
        else value
        for key, value in values.items()
    }


class ContextualConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._name = user_input["name"].strip() or NAME
            return await self.async_step_entities()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("name", default=NAME): selector.TextSelector()}),
        )

    async def async_step_entities(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=self._name, data={}, options={**deepcopy(DEFAULTS), **normalize(user_input)}
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
        return self.async_show_menu(step_id="init", menu_options=[*SECTIONS, "reset"])

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

    async def async_step_dashboard(self, user_input=None):
        return await self._section("dashboard", user_input)

    async def async_step_advanced(self, user_input=None):
        return await self._section("advanced", user_input)

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
