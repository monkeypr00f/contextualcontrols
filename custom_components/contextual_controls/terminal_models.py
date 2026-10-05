"""Terminal presentation/configuration, without a second ranking engine."""

from __future__ import annotations

from typing import Any

MAX_ITEMS = 20
PROFILE_DEFAULTS: dict[str, Any] = {
    "terminal_name": "",
    "zone_name": "",
    "fixed_entities": [],
    "contextual_enabled": True,
    "contextual_max_items": 5,
    "dim_timeout": 30,
    "off_timeout": 120,
}


def normalize_profile(values: dict[str, Any]) -> dict[str, Any]:
    profile = {**PROFILE_DEFAULTS, **values}
    fixed = profile["fixed_entities"]
    if not isinstance(fixed, list) or any(
        not isinstance(entity, str) or "." not in entity for entity in fixed
    ):
        raise ValueError("invalid fixed entities")
    profile["fixed_entities"] = list(dict.fromkeys(fixed))
    profile["contextual_max_items"] = int(profile["contextual_max_items"])
    profile["dim_timeout"] = int(profile["dim_timeout"])
    profile["off_timeout"] = int(profile["off_timeout"])
    if (
        len(profile["fixed_entities"]) > MAX_ITEMS
        or not 0 <= profile["contextual_max_items"] <= 12
        or not 5 <= profile["dim_timeout"] <= 3600
        or not profile["dim_timeout"] < profile["off_timeout"] <= 7200
    ):
        raise ValueError("invalid terminal limits")
    for field in ("terminal_name", "zone_name"):
        profile[field] = str(profile[field]).strip()[:80]
    profile["contextual_enabled"] = bool(profile["contextual_enabled"])
    return {key: profile[key] for key in PROFILE_DEFAULTS}


def compose_items(fixed: list[str], dynamic: list[str], max_dynamic: int) -> list[tuple[str, str]]:
    """Fixed position wins; suggestions never duplicate a fixed item."""
    fixed = list(dict.fromkeys(fixed))[:MAX_ITEMS]
    seen = set(fixed)
    suggestions = []
    for entity in dynamic:
        if entity not in seen:
            suggestions.append((entity, "contextual"))
            seen.add(entity)
    return [(entity, "fixed") for entity in fixed] + suggestions[
        : min(max_dynamic, MAX_ITEMS - len(fixed))
    ]


def state_text(domain: str, state: str, attributes: dict[str, Any], language: str = "it") -> str:
    """Small server-language vocabulary; never depend on frontend JS translations."""
    italian = language.startswith("it")
    if state in {"unavailable", "unknown"}:
        return (
            {"unavailable": "Non disponibile", "unknown": "Sconosciuto"}.get(state, state)
            if italian
            else state.replace("_", " ").title()
        )
    if domain == "light":
        if state == "off":
            return "Spenta" if italian else "Off"
        value = attributes.get("brightness")
        suffix = f" · {round(value * 100 / 255)}%" if isinstance(value, (int, float)) else ""
        return ("Accesa" if italian else "On") + suffix
    if domain in {"switch", "input_boolean", "fan"}:
        return {"on": "Acceso", "off": "Spento"}.get(state, state) if italian else state.title()
    if domain == "climate":
        unit = attributes.get("temperature_unit", "°C")
        current = attributes.get("current_temperature")
        target = attributes.get("temperature")
        hvac = attributes.get("hvac_action", state)
        translated = {
            "heating": "Riscaldamento",
            "heat": "Riscaldamento",
            "cooling": "Raffrescamento",
            "cool": "Raffrescamento",
            "idle": "In attesa",
            "off": "Spento",
            "auto": "Automatico",
            "heat_cool": "Caldo / freddo",
            "dry": "Deumidificazione",
            "fan_only": "Ventilazione",
        }.get(hvac, str(hvac))
        text = translated if italian else str(hvac).replace("_", " ").title()
        if current is not None:
            text += f" · {current} {unit}"
        if target is not None:
            text += f" / {target} {unit}"
        return text
    return state.replace("_", " ")
