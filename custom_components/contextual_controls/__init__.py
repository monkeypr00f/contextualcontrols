"""Contextual Controls: local suggestions, never autonomous device actions."""

from .const import DOMAIN


async def async_migrate_entry(hass, entry):
    """Migrate old source names and populate current option defaults."""
    if entry.version > 5:
        return False
    if entry.version < 5:
        from copy import deepcopy

        from .const import DEFAULTS

        options = {**deepcopy(DEFAULTS), **entry.options}
        if entry.version < 2:
            source_map = {"user": "manual", "child": "unknown", "unknown": "unknown"}
            options["learn_sources"] = list(
                dict.fromkeys(source_map.get(source, source) for source in options["learn_sources"])
            )
        hass.config_entries.async_update_entry(entry, options=options, version=5)
    return True


async def async_setup(hass, config):
    """Register integration actions once, independent of loaded entries."""
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import ServiceValidationError
    from homeassistant.helpers import config_validation as cv

    def coordinator_for(call):
        entry_id = call.data.get("config_entry_id")
        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if getattr(entry, "runtime_data", None) is not None
            and (entry_id is None or entry.entry_id == entry_id)
        ]
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        if len(entries) > 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_required"
            )
        return entries[0].runtime_data

    async def reset_learning(call):
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if entry is None or entry.domain != DOMAIN or not getattr(entry, "runtime_data", None):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        if not call.data["confirm"]:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="confirmation_required"
            )
        mode = call.data["mode"]
        if mode == "user" and not call.data.get("user_id"):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="user_required")
        if mode == "entity" and not call.data.get("entity_id"):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entity_required"
            )
        await entry.runtime_data.history.async_reset_mode(
            mode,
            call.data.get("entity_id"),
            call.data.get("user_id"),
        )
        await entry.runtime_data.async_refresh()

    hass.services.async_register(
        DOMAIN,
        "reset_learning",
        reset_learning,
        schema=vol.Schema(
            {
                vol.Required("config_entry_id"): cv.string,
                vol.Required("confirm", default=False): cv.boolean,
                vol.Required("mode", default="all"): vol.In(
                    ("all", "historical", "sequence", "feedback", "user", "entity")
                ),
                vol.Optional("entity_id"): cv.entity_id,
                vol.Optional("user_id"): cv.string,
            }
        ),
    )

    async def get_learning_stats(call):
        return coordinator_for(call).learning_stats(
            call.data.get("entity_id"), call.data.get("user_id")
        )

    hass.services.async_register(
        DOMAIN,
        "get_learning_stats",
        get_learning_stats,
        schema=vol.Schema(
            {
                vol.Optional("config_entry_id"): cv.string,
                vol.Optional("entity_id"): cv.entity_id,
                vol.Optional("user_id"): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    slot_schema = {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("slot"): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
    }

    async def get_slot(call):
        return coordinator_for(call).quick_access_slot(call.data["slot"])

    hass.services.async_register(
        DOMAIN,
        "get_slot",
        get_slot,
        schema=vol.Schema(slot_schema),
        supports_response=SupportsResponse.ONLY,
    )

    async def execute_slot(call):
        coordinator = coordinator_for(call)
        response = await coordinator.async_execute_slot(
            call.data["slot"],
            expected_entity_id=call.data.get("expected_entity_id"),
            mode=call.data["mode"],
            confirmed=call.data["confirmed"],
            source=call.data["source"],
            context=call.context,
        )
        if coordinator.options["quick_access_response"] and call.return_response:
            return response
        return None

    hass.services.async_register(
        DOMAIN,
        "execute_slot",
        execute_slot,
        schema=vol.Schema(
            {
                **slot_schema,
                vol.Optional("expected_entity_id"): cv.entity_id,
                vol.Required("mode", default="automatic"): vol.In(
                    ("automatic", "more_info", "execute")
                ),
                vol.Required("confirmed", default=False): cv.boolean,
                vol.Required("source", default="unknown"): vol.In(
                    (
                        "apple_watch",
                        "ios_lock_screen",
                        "shortcut",
                        "action_button",
                        "control_center",
                        "unknown",
                    )
                ),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    terminal_schema = vol.Schema(
        {
            vol.Optional("config_entry_id"): cv.string,
            vol.Required("terminal"): cv.slug,
            vol.Required("input"): vol.In(("select", "activate", "adjust", "back")),
            vol.Optional("slot"): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
            vol.Optional("delta"): vol.All(vol.Coerce(int), vol.Range(min=-20, max=20)),
            vol.Optional("revision"): cv.string,
        }
    )

    async def terminal_input(call):
        coordinator = coordinator_for(call)
        return await coordinator.terminal_manager.async_input(
            call.data["terminal"],
            call.data["input"],
            call.data.get("slot"),
            call.data.get("delta"),
            call.data.get("revision"),
            call.context,
        )

    hass.services.async_register(
        DOMAIN,
        "terminal_input",
        terminal_input,
        schema=terminal_schema,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def refresh_terminal(call):
        coordinator = coordinator_for(call)
        await coordinator.terminal_manager.async_publish(call.data["terminal"])

    hass.services.async_register(
        DOMAIN,
        "refresh_terminal",
        refresh_terminal,
        schema=vol.Schema(
            {vol.Optional("config_entry_id"): cv.string, vol.Required("terminal"): cv.slug}
        ),
    )
    return True


async def async_setup_entry(hass, entry):
    from homeassistant.const import Platform
    from homeassistant.exceptions import ConfigEntryNotReady, UnsupportedStorageVersionError

    from .coordinator import ContextualCoordinator

    coordinator = ContextualCoordinator(hass, entry)
    try:
        await coordinator.async_initialize()
    except (OSError, ValueError, UnsupportedStorageVersionError) as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="storage_unavailable"
        ) from err
    entry.runtime_data = coordinator
    try:
        await coordinator.async_config_entry_first_refresh()
        await coordinator.terminal_manager.async_configure()
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    except Exception:
        await coordinator.async_close()
        raise
    return True


async def async_unload_entry(hass, entry):
    from homeassistant.const import Platform

    if await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        await entry.runtime_data.async_close()
        entry.runtime_data = None
        return True
    return False


async def async_remove_entry(hass, entry):
    from .storage import History

    await History(hass, entry.entry_id).store.async_remove()
