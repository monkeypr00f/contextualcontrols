"""Physical Context Dial projection backed by the existing coordinator ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.util import dt as dt_util

from .quick_access import DEFAULT_ICONS, SlotManager

if TYPE_CHECKING:
    from .coordinator import ContextualCoordinator

MAX_TERMINAL_ACTIONS = 5
EVENT_TERMINAL_INPUT = "contextual_controls_terminal_input"


def parse_terminal_mappings(value: str) -> dict[str, tuple[str, ...]]:
    """Parse `terminal:area+area` pairs without accepting ambiguous identifiers."""
    mappings: dict[str, tuple[str, ...]] = {}
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        terminal, separator, raw_area_ids = item.partition(":")
        terminal = terminal.strip()
        area_ids = tuple(area_id.strip() for area_id in raw_area_ids.split("+"))
        if not separator or not terminal or not all(area_ids):
            raise ValueError("terminal mappings must use terminal_id:area_id[+area_id]")
        if terminal in mappings:
            raise ValueError(f"duplicate terminal id: {terminal}")
        if (
            not terminal.replace("_", "").isalnum()
            or any(not area_id.replace("_", "").isalnum() for area_id in area_ids)
            or len(set(area_ids)) != len(area_ids)
        ):
            raise ValueError(
                "terminal and area ids may contain only letters, numbers and underscores"
            )
        mappings[terminal] = area_ids
    return mappings


@dataclass(slots=True)
class TerminalSession:
    terminal_id: str
    area_ids: tuple[str, ...]
    slots: SlotManager
    mode: str = "menu"
    active_slot: int | None = None
    feedback: str = "ready"
    adjusted_action: str | None = None


class TerminalManager:
    """Publish a five-row projection; execute only coordinator-owned slots."""

    def __init__(self, hass: HomeAssistant, coordinator: ContextualCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.sessions: dict[str, TerminalSession] = {}

    async def async_configure(self) -> None:
        mappings = parse_terminal_mappings(self.coordinator.options["terminal_mappings"])
        old = self.sessions
        self.sessions = {}
        for terminal_id, area_ids in mappings.items():
            existing = old.get(terminal_id)
            if existing is not None and existing.area_ids == area_ids:
                self.sessions[terminal_id] = existing
                continue
            self.sessions[terminal_id] = TerminalSession(
                terminal_id,
                area_ids,
                SlotManager(
                    MAX_TERMINAL_ACTIONS,
                    int(self.coordinator.options["quick_access_stability"]),
                ),
            )
        await self.async_publish_all()

    async def async_publish_all(self) -> None:
        for terminal_id in self.sessions:
            await self.async_publish(terminal_id)

    async def async_publish(self, terminal_id: str) -> None:
        session = self._session(terminal_id)
        now = dt_util.now()
        rows = [
            row
            for row in self.coordinator.terminal_rows
            if self.coordinator.areas.get(row["entity_id"]) in session.area_ids
        ]
        # Do not replace the target under an editing user when ranking changes.
        if session.mode != "adjust":
            session.slots.update(rows, now, self.coordinator._quick_target_valid)
        registry = ar.async_get(self.hass)
        title = " · ".join(
            area.name
            if (area := registry.async_get_area(area_id))
            else area_id.replace("_", " ").title()
            for area_id in session.area_ids
        )
        prefix = f"sensor.contextual_controls_{terminal_id}"
        self.hass.states.async_set(f"{prefix}_title", title, {"terminal": terminal_id})
        self.hass.states.async_set(
            f"{prefix}_status",
            f"{sum(item is not None for item in session.slots.slots)} controlli disponibili"
            if any(session.slots.slots)
            else "Nessuna azione disponibile",
            {
                "terminal": terminal_id,
                "area_id": session.area_ids[0],
                "area_ids": list(session.area_ids),
            },
        )
        self.hass.states.async_set(f"{prefix}_mode", session.mode, {"terminal": terminal_id})
        # This is deliberately a separate state rather than an attribute: ESPHome's
        # Home Assistant text sensor consumes states, not arbitrary attributes.
        self.hass.states.async_set(
            f"{prefix}_feedback", session.feedback, {"terminal": terminal_id}
        )
        self.hass.states.async_set(
            f"{prefix}_revision", str(session.slots.generation), {"terminal": terminal_id}
        )
        for slot in range(1, MAX_TERMINAL_ACTIONS + 1):
            detail = self._slot_detail(session, slot)
            self.hass.states.async_set(f"{prefix}_action_{slot}", detail.get("label", ""), detail)

    async def async_input(
        self,
        terminal_id: str,
        input_name: str,
        slot: int | None,
        delta: int | None,
        revision: str | None,
        context: Context,
    ) -> dict[str, Any]:
        session = self._session(terminal_id)
        if revision is not None and revision != str(session.slots.generation):
            session.feedback = "stale"
            await self.async_publish(terminal_id)
            return {"success": False, "reason": "stale_revision"}
        if input_name == "back":
            if session.adjusted_action and session.active_slot is not None:
                await self._track_adjustment(session, context)
            session.feedback = "ready"
            if session.mode == "adjust":
                session.mode, session.active_slot = "menu", None
            await self.async_publish(terminal_id)
            return {"success": True, "mode": session.mode}
        if slot is None or not 1 <= slot <= MAX_TERMINAL_ACTIONS:
            return {"success": False, "reason": "invalid_slot"}
        selected = (
            session.active_slot
            if session.mode == "adjust" and session.active_slot is not None
            else slot
        )
        detail = self._slot_detail(session, selected)
        if not detail.get("available"):
            session.feedback = "empty"
            await self.async_publish(terminal_id)
            return {"success": False, "reason": "empty_slot"}
        if input_name == "select" and session.mode == "adjust":
            result = await self.coordinator.async_adjust_terminal_slot(
                detail["entity_id"], delta or 0, context
            )
            if result.get("success"):
                session.adjusted_action = result.get("action", "adjust")
            await self._emit(terminal_id, session, "adjust", selected, detail, result)
            # A successful tick is still an editing operation, not a completed
            # command. Keep the dial on its value-control view until press.
            session.feedback = (
                "adjust" if result.get("success") else str(result.get("reason", "error"))
            )
            await self.async_publish(terminal_id)
            return result
        if input_name == "adjust" and detail["kind"] == "LIGHT":
            session.mode, session.active_slot = "adjust", selected
            session.adjusted_action = None
            session.feedback = "adjust"
            await self._emit(
                terminal_id, session, "enter_adjust", selected, detail, {"success": True}
            )
            await self.async_publish(terminal_id)
            return {"success": True, "mode": session.mode}
        if input_name == "activate" and (
            detail["kind"] in {"NUMBER", "CLIMATE", "MEDIA"}
            or (detail["kind"] == "LIGHT" and session.mode == "adjust")
        ):
            if session.mode == "adjust":
                await self._track_adjustment(session, context)
                session.mode, session.active_slot = "menu", None
                await self._emit(
                    terminal_id, session, "confirm", selected, detail, {"success": True}
                )
                session.feedback = "ok"
            else:
                session.mode, session.active_slot = "adjust", selected
                session.adjusted_action = None
                await self._emit(
                    terminal_id, session, "enter_adjust", selected, detail, {"success": True}
                )
                session.feedback = "adjust"
            await self.async_publish(terminal_id)
            return {"success": True, "mode": session.mode}
        if input_name != "activate":
            result = {"success": True, "reason": "selection_recorded"}
            await self._emit(terminal_id, session, "select", selected, detail, result)
            return result
        # Ensure repeated successes produce distinct HA state transitions so
        # the Dial never waits forever for a second identical "ok" response.
        session.feedback = "loading"
        await self.async_publish(terminal_id)
        result = await self.coordinator.async_execute_terminal_entity(
            detail["entity_id"], selected, context
        )
        await self._emit(terminal_id, session, "activate", selected, detail, result)
        session.feedback = "ok" if result.get("success") else str(result.get("reason", "error"))
        await self.async_publish(terminal_id)
        return result

    async def _track_adjustment(self, session: TerminalSession, context: Context) -> None:
        if session.adjusted_action and session.active_slot is not None:
            snapshot = session.slots.get(session.active_slot)
            if snapshot is not None:
                await self.coordinator._async_track_terminal_usage(
                    snapshot.entity_id, session.adjusted_action, session.active_slot, context
                )
            session.adjusted_action = None

    async def _emit(
        self,
        terminal_id: str,
        session: TerminalSession,
        input_name: str,
        selected: int,
        detail: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        self.hass.bus.async_fire(
            EVENT_TERMINAL_INPUT,
            {
                "timestamp": dt_util.utcnow().isoformat(),
                "terminal": terminal_id,
                "area_id": session.area_ids[0],
                "area_ids": list(session.area_ids),
                "input": input_name,
                "slot": selected,
                "position": selected,
                "mode": session.mode,
                "revision": session.slots.generation,
                "action_id": detail["entity_id"],
                "available_action_ids": [
                    item.entity_id for item in session.slots.slots if item is not None
                ],
                "success": bool(result.get("success")),
            },
        )

    def _slot_detail(self, session: TerminalSession, slot: int) -> dict[str, Any]:
        snapshot = session.slots.get(slot)
        if snapshot is None:
            return {"slot": slot, "available": False, "label": ""}
        entity_id = snapshot.entity_id
        state = self.hass.states.get(entity_id)
        if state is None or not self.coordinator._quick_target_valid(entity_id):
            return {"slot": slot, "available": False, "label": ""}
        domain = entity_id.partition(".")[0]
        kind = {"number": "NUMBER", "climate": "CLIMATE", "media_player": "MEDIA"}.get(
            domain,
            "TOGGLE" if domain in {"light", "switch", "fan", "input_boolean"} else "ACTION",
        )
        # A dimmer/position is a value control; a simple light remains a
        # toggle. This keeps the projected type truthful to actual capability.
        if domain == "light" and self._light_supports_brightness(state.attributes):
            kind = "LIGHT"
        elif domain == "cover" and isinstance(state.attributes.get("current_position"), int):
            kind = "NUMBER"
        label = str(state.attributes.get("friendly_name", entity_id))
        if kind in {"NUMBER", "CLIMATE", "MEDIA", "LIGHT"}:
            value_label = self._value_label(domain, state.state, state.attributes)
            label = f"{label}: {value_label}" if value_label else label
        value, minimum, maximum, step, unit = self._control_values(
            domain, state.state, state.attributes
        )
        return {
            "slot": slot,
            "available": True,
            "entity_id": entity_id,
            "label": label,
            "kind": kind,
            "icon": state.attributes.get("icon") or DEFAULT_ICONS.get(domain),
            "state": state.state,
            "score": snapshot.score,
            "rank_reason": snapshot.reason,
            # A complete projection lets non-ESPHome clients render native
            # controls too. The Dial itself needs only label/kind; HA remains
            # authoritative for all limits and the actual adjustment.
            "value": value,
            "min": minimum,
            "max": maximum,
            "step": step,
            "unit": unit,
        }

    @staticmethod
    def _value_label(domain: str, state: str, attributes: dict[str, Any]) -> str:
        if domain == "media_player":
            volume = attributes.get("volume_level")
            return f"{round(float(volume) * 100)}%" if isinstance(volume, (float, int)) else state
        if domain == "climate":
            value = attributes.get("temperature")
            return f"{value}°" if value is not None else state
        if domain == "light":
            return f"{round((attributes.get('brightness') or 0) * 100 / 255)}%"
        if domain == "cover" and isinstance(attributes.get("current_position"), int):
            return f"{attributes['current_position']}%"
        return state

    @staticmethod
    def _control_values(
        domain: str, state: str, attributes: dict[str, Any]
    ) -> tuple[float | str | None, float | None, float | None, float | None, str]:
        """Normalize value metadata without making device-specific assumptions."""
        if domain == "number":
            minimum = attributes.get("min")
            maximum = attributes.get("max")
            if minimum is None or maximum is None:
                return None, None, None, None, ""
            try:
                return (
                    float(state),
                    float(minimum),
                    float(maximum),
                    float(attributes.get("step", 1)),
                    str(attributes.get("unit_of_measurement", "")),
                )
            except TypeError, ValueError:
                return None, None, None, None, ""
        if domain == "climate":
            value = attributes.get("temperature")
            if isinstance(value, (int, float)):
                return (
                    value,
                    float(attributes.get("min_temp", value)),
                    float(attributes.get("max_temp", value)),
                    float(attributes.get("target_temp_step", 0.5)),
                    str(attributes.get("temperature_unit", "°C")),
                )
        if domain == "media_player":
            value = attributes.get("volume_level")
            if isinstance(value, (int, float)):
                return round(value * 100), 0, 100, 5, "%"
        if domain == "light":
            return round((attributes.get("brightness") or 0) * 100 / 255), 0, 100, 5, "%"
        if domain == "cover" and isinstance(attributes.get("current_position"), int):
            return attributes["current_position"], 0, 100, 5, "%"
        return state, None, None, None, ""

    @staticmethod
    def _light_supports_brightness(attributes: dict[str, Any]) -> bool:
        """Brightness is exposed by HA only for lights that can be dimmed."""
        if "brightness" in attributes:
            return True
        color_modes = attributes.get("supported_color_modes", [])
        return any(
            mode in {"brightness", "color_temp", "hs", "xy", "rgb", "rgbw", "rgbww"}
            for mode in color_modes
        )

    def _session(self, terminal_id: str) -> TerminalSession:
        try:
            return self.sessions[terminal_id]
        except KeyError as err:
            raise ValueError(f"unknown terminal: {terminal_id}") from err
