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


def parse_terminal_mappings(value: str) -> dict[str, str]:
    """Parse `terminal:area` pairs without accepting ambiguous identifiers."""
    mappings: dict[str, str] = {}
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        terminal, separator, area_id = item.partition(":")
        terminal = terminal.strip()
        area_id = area_id.strip()
        if not separator or not terminal or not area_id:
            raise ValueError("terminal mappings must use terminal_id:area_id")
        if terminal in mappings:
            raise ValueError(f"duplicate terminal id: {terminal}")
        if not terminal.replace("_", "").isalnum() or not area_id.replace("_", "").isalnum():
            raise ValueError(
                "terminal and area ids may contain only letters, numbers and underscores"
            )
        mappings[terminal] = area_id
    return mappings


@dataclass(slots=True)
class TerminalSession:
    terminal_id: str
    area_id: str
    slots: SlotManager
    mode: str = "menu"
    active_slot: int | None = None


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
        for terminal_id, area_id in mappings.items():
            existing = old.get(terminal_id)
            if existing is not None and existing.area_id == area_id:
                self.sessions[terminal_id] = existing
                continue
            self.sessions[terminal_id] = TerminalSession(
                terminal_id,
                area_id,
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
            for row in (self.coordinator.data or {}).get("entities", [])
            if self.coordinator.areas.get(row["entity_id"]) == session.area_id
        ]
        session.slots.update(rows, now, self.coordinator._quick_target_valid)
        area = ar.async_get(self.hass).async_get_area(session.area_id)
        title = area.name if area else session.area_id.replace("_", " ").title()
        prefix = f"sensor.contextual_controls_{terminal_id}"
        self.hass.states.async_set(f"{prefix}_title", title, {"terminal": terminal_id})
        self.hass.states.async_set(
            f"{prefix}_status",
            "Controlli suggeriti" if any(session.slots.slots) else "Nessuna azione disponibile",
            {"terminal": terminal_id, "area_id": session.area_id},
        )
        self.hass.states.async_set(f"{prefix}_mode", session.mode, {"terminal": terminal_id})
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
            await self.async_publish(terminal_id)
            return {"success": False, "reason": "stale_revision"}
        if input_name == "back":
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
            await self.async_publish(terminal_id)
            return {"success": False, "reason": "empty_slot"}
        if input_name == "select" and session.mode == "adjust":
            result = await self.coordinator.async_adjust_terminal_slot(
                detail["entity_id"], delta or 0, context
            )
            await self._emit(terminal_id, session, "adjust", selected, detail, result)
            await self.async_publish(terminal_id)
            return result
        if input_name == "adjust" and detail["kind"] == "LIGHT":
            session.mode, session.active_slot = "adjust", selected
            await self._emit(
                terminal_id, session, "enter_adjust", selected, detail, {"success": True}
            )
            await self.async_publish(terminal_id)
            return {"success": True, "mode": session.mode}
        if input_name == "activate" and detail["kind"] in {"NUMBER", "CLIMATE", "MEDIA"}:
            if session.mode == "adjust":
                session.mode, session.active_slot = "menu", None
                await self._emit(
                    terminal_id, session, "confirm", selected, detail, {"success": True}
                )
            else:
                session.mode, session.active_slot = "adjust", selected
                await self._emit(
                    terminal_id, session, "enter_adjust", selected, detail, {"success": True}
                )
            await self.async_publish(terminal_id)
            return {"success": True, "mode": session.mode}
        if input_name != "activate":
            result = {"success": True, "reason": "selection_recorded"}
            await self._emit(terminal_id, session, "select", selected, detail, result)
            return result
        result = await self.coordinator.async_execute_terminal_entity(
            detail["entity_id"], selected, context
        )
        await self._emit(terminal_id, session, "activate", selected, detail, result)
        await self.async_publish(terminal_id)
        return result

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
                "area_id": session.area_id,
                "input": input_name,
                "slot": selected,
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
        if domain == "light" and self._light_supports_brightness(state.attributes):
            kind = "LIGHT"
        label = str(state.attributes.get("friendly_name", entity_id))
        if kind in {"NUMBER", "CLIMATE", "MEDIA", "LIGHT"}:
            value = self._value_label(domain, state.state, state.attributes)
            label = f"{label}: {value}" if value else label
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
        }

    @staticmethod
    def _value_label(domain: str, state: str, attributes: dict[str, Any]) -> str:
        if domain == "light":
            brightness = attributes.get("brightness")
            if isinstance(brightness, (float, int)):
                return f"{round(float(brightness) / 255 * 100)}%"
            return "spenta" if state == "off" else state
        if domain == "media_player":
            volume = attributes.get("volume_level")
            return f"{round(float(volume) * 100)}%" if isinstance(volume, (float, int)) else state
        if domain == "climate":
            value = attributes.get("temperature")
            return f"{value}°" if value is not None else state
        return state

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
