"""Serve and register the bundled preview Lovelace card."""

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import VERSION

CARD_URL = "/contextual_controls/contextual-controls-card.js"
CARD_MODULE_URL = f"{CARD_URL}?v={VERSION}"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Expose the card and load it as an extra frontend module."""
    path = Path(__file__).parent / "frontend" / "contextual-controls-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=True)]
    )
    add_extra_js_url(hass, CARD_MODULE_URL)
