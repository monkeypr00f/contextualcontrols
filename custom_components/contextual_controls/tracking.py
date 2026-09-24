"""Conservative origin classification and supported control actions."""

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
    "lock": {"lock", "unlock", "open"},
    "vacuum": {"start", "pause", "stop", "return_to_base", "clean_spot", "set_fan_speed"},
    "select": {"select_option", "select_next", "select_previous", "select_first", "select_last"},
    "number": {"set_value"},
}


def classify(user_id: str | None, parent_id: str | None) -> tuple[str, float]:
    """Do not label child contexts as UI or guess Assist/automation ancestry."""
    if parent_id:
        return "child", 0.3
    if user_id:
        return "user", 0.9
    return "unknown", 0.2


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
