"""Conservative origin classification and supported control actions."""

from __future__ import annotations

from collections import OrderedDict

ON_OFF = {"turn_on", "turn_off", "toggle"}
ACTIONS = {
    "light": ON_OFF,
    "switch": ON_OFF,
    "input_boolean": ON_OFF,
    "fan": ON_OFF | {"set_percentage", "set_preset_mode", "oscillate", "set_direction"},
    "cover": {
        "open_cover",
        "close_cover",
        "stop_cover",
        "set_cover_position",
        "toggle",
        "open_cover_tilt",
        "close_cover_tilt",
        "stop_cover_tilt",
        "set_cover_tilt_position",
    },
    "climate": ON_OFF
    | {
        "set_temperature",
        "set_hvac_mode",
        "set_preset_mode",
        "set_fan_mode",
        "set_humidity",
        "set_swing_mode",
    },
    "media_player": ON_OFF
    | {
        "media_play",
        "media_pause",
        "media_play_pause",
        "media_stop",
        "play_media",
        "volume_set",
        "volume_up",
        "volume_down",
        "volume_mute",
        "select_source",
        "select_sound_mode",
        "media_next_track",
        "media_previous_track",
    },
    "scene": {"turn_on"},
    "script": {"turn_on", "turn_off", "toggle"},
    "button": {"press"},
    "input_button": {"press"},
    "lock": {"lock", "unlock", "open"},
    "alarm_control_panel": {
        "alarm_arm_home",
        "alarm_arm_away",
        "alarm_arm_night",
        "alarm_arm_vacation",
        "alarm_arm_custom_bypass",
        "alarm_disarm",
        "alarm_trigger",
    },
    "siren": {"turn_on", "turn_off", "toggle"},
    "vacuum": {"start", "pause", "stop", "return_to_base", "clean_spot", "set_fan_speed"},
    "select": {"select_option", "select_next", "select_previous", "select_first", "select_last"},
    "number": {"set_value"},
}


SOURCE_CONFIDENCE = {
    "manual": 0.95,
    "assist": 0.85,
    "script": 0.65,
    "automation": 0.55,
    "unknown": 0.2,
}


def classify(
    context_id: str,
    user_id: str | None,
    parent_id: str | None,
    origins: OriginTracker | None = None,
) -> tuple[str, float]:
    """Prefer observed ancestry; only root authenticated calls are manual."""
    if origins and (source := origins.resolve(context_id, parent_id)):
        return source, SOURCE_CONFIDENCE[source]
    if user_id and not parent_id:
        return "manual", SOURCE_CONFIDENCE["manual"]
    return "unknown", 0.25 if parent_id else SOURCE_CONFIDENCE["unknown"]


class OriginTracker:
    """Bounded in-memory index of public HA execution-context events."""

    def __init__(self) -> None:
        self._origins: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def observe(self, context_id: str, source: str, now: float) -> None:
        while self._origins and (
            now - next(iter(self._origins.values()))[1] > 300 or len(self._origins) >= 4096
        ):
            self._origins.popitem(last=False)
        self._origins[context_id] = (source, now)

    def resolve(self, context_id: str, parent_id: str | None) -> str | None:
        current = self._origins.get(context_id)
        if current:
            return current[0]
        if parent_id and (parent := self._origins.get(parent_id)):
            return parent[0]
        return None


def supports_action(entity_id: str, domain: str, action: str) -> bool:
    """Reject queries and mismatched domains, including expanded area targets."""
    entity_domain = entity_id.partition(".")[0]
    if domain not in (entity_domain, "homeassistant"):
        return False
    if domain == "homeassistant" and action not in ON_OFF:
        return False
    return action in ACTIONS.get(entity_domain, set())


class Deduplicator:
    """Bound memory and collapse identical context/entity/action events for 5s."""

    def __init__(self) -> None:
        self._seen: OrderedDict[tuple[str, str, str], float] = OrderedDict()

    def accept(self, context_id: str, entity: str, action: str, now: float) -> bool:
        while self._seen and (now - next(iter(self._seen.values())) > 5 or len(self._seen) >= 2048):
            self._seen.popitem(last=False)
        key = (context_id, entity, action)
        if key in self._seen:
            return False
        self._seen[key] = now
        return True
