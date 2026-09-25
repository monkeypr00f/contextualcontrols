"""Declare UI-only configuration via Home Assistant's public validation hook."""

from homeassistant.helpers import config_validation as cv

from .const import DOMAIN


async def async_validate_config(hass, config):
    """Reject YAML configuration using HA's standard config-entry-only schema."""
    return cv.config_entry_only_config_schema(DOMAIN)(config)
