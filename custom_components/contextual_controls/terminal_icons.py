"""MDI font projection. Unknown/custom icon providers use an explicit fallback."""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _codepoints() -> dict[str, str]:
    path = Path(__file__).with_name("mdi_metadata.json")
    return {
        f"mdi:{item['name']}": chr(int(item["codepoint"], 16))
        for item in json.loads(path.read_text())
    }


def icon_glyph(icon: str) -> str:
    return _codepoints().get(icon, "\U000f02d7")


def default_icon(domain: str, device_class: str | None) -> str | None:
    classes = {
        "temperature": "mdi:thermometer",
        "humidity": "mdi:water-percent",
        "motion": "mdi:motion-sensor",
        "door": "mdi:door",
        "window": "mdi:window-closed",
        "battery": "mdi:battery",
        "power": "mdi:flash",
        "energy": "mdi:lightning-bolt",
    }
    if device_class in classes:
        return classes[device_class]
    return {
        "light": "mdi:lightbulb",
        "switch": "mdi:toggle-switch",
        "climate": "mdi:thermostat",
        "sensor": "mdi:eye",
        "binary_sensor": "mdi:checkbox-marked-circle-outline",
    }.get(domain)
