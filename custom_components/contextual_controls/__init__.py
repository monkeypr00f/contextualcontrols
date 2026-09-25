"""Contextual Controls: local suggestions, never autonomous device actions."""

from .const import DOMAIN


async def async_migrate_entry(hass, entry):
    """Migrate old source names and populate defaults through Phase 3."""
    if entry.version > 3:
        return False
    if entry.version < 3:
        from copy import deepcopy

        from .const import DEFAULTS

        options = {**deepcopy(DEFAULTS), **entry.options}
        if entry.version < 2:
            source_map = {"user": "manual", "child": "unknown", "unknown": "unknown"}
            options["learn_sources"] = list(
                dict.fromkeys(source_map.get(source, source) for source in options["learn_sources"])
            )
        hass.config_entries.async_update_entry(entry, options=options, version=3)
    return True


async def async_setup(hass, config):
    """Register integration actions once, independent of loaded entries."""
    import voluptuous as vol
    from homeassistant.exceptions import ServiceValidationError
    from homeassistant.helpers import config_validation as cv

    # A normal UI-configured Home Assistant already has frontend and HTTP.
    # Keep the statistical backend usable in headless/test runtimes as well.
    if "frontend" in hass.config.components and hasattr(hass, "http"):
        from .frontend import async_register_frontend

        await async_register_frontend(hass)

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
        await entry.runtime_data.history.async_reset(
            call.data.get("entity_id"), call.data.get("user_id")
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
                vol.Optional("entity_id"): cv.entity_id,
                vol.Optional("user_id"): cv.string,
            }
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
