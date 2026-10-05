"""Physical Context Dial projection backed by the existing coordinator ranking."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.util import dt as dt_util

from .quick_access import DEFAULT_ICONS, SlotManager
from .terminal_icons import default_icon, icon_glyph
from .terminal_models import MAX_ITEMS, compose_items, normalize_profile, state_text

if TYPE_CHECKING:
    from .coordinator import ContextualCoordinator

MAX_TERMINAL_ACTIONS = MAX_ITEMS
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
    profile: dict[str, Any] = field(default_factory=lambda: normalize_profile({}))
    pending_value: float | None = None
    initial_value: Any = None


class TerminalManager:
    """Project configurable fixed controls plus the existing ranked suggestions."""

    def __init__(self, hass: HomeAssistant, coordinator: ContextualCoordinator) -> None:
        self.hass, self.coordinator = hass, coordinator
        self.sessions: dict[str, TerminalSession] = {}
        # Do not accept cached slot revisions after an integration restart.
        self._generation = int(dt_util.utcnow().timestamp() * 1_000_000)

    async def async_configure(self) -> None:
        # Load the bundled MDI map outside HA's event loop, once per process.
        await asyncio.to_thread(icon_glyph, "mdi:help-circle")
        mappings = parse_terminal_mappings(self.coordinator.options["terminal_mappings"])
        old = self.sessions
        self.sessions = {}
        for terminal_id, areas in mappings.items():
            profile = normalize_profile(
                self.coordinator.options.get("terminal_settings", {}).get(terminal_id, {})
            )
            existing = old.get(terminal_id)
            if existing and existing.area_ids == areas and existing.profile == profile:
                self.sessions[terminal_id] = existing
            else:
                self.sessions[terminal_id] = TerminalSession(
                    terminal_id,
                    areas,
                    SlotManager(MAX_ITEMS, int(self.coordinator.options["quick_access_stability"])),
                    profile=profile,
                )
        await self.async_publish_all()

    def is_fixed(self, entity_id: str) -> bool:
        return any(entity_id in s.profile["fixed_entities"] for s in self.sessions.values())

    async def async_publish_all(self) -> None:
        for terminal_id in tuple(self.sessions):
            await self.async_publish(terminal_id)

    async def async_publish(self, terminal_id: str) -> None:
        session = self._session(terminal_id)
        fixed = session.profile["fixed_entities"]
        dynamic = [
            row
            for row in self.coordinator.terminal_rows
            if self.coordinator.areas.get(row["entity_id"]) in session.area_ids
        ]
        by_id = {row["entity_id"]: row for row in dynamic}
        count = (
            session.profile["contextual_max_items"] if session.profile["contextual_enabled"] else 0
        )
        pairs = compose_items(fixed, [row["entity_id"] for row in dynamic], count)
        rows = [
            {**by_id.get(entity, {}), "entity_id": entity, "source": source}
            for entity, source in pairs
        ]
        if session.mode != "adjust":
            changed = session.slots.update(
                rows,
                dt_util.now(),
                lambda entity: entity in fixed or self.coordinator._quick_target_valid(entity),
            )
            if changed:
                self._generation += 1
                session.slots.generation = self._generation
        registry = ar.async_get(self.hass)
        title = session.profile["zone_name"] or " · ".join(
            area.name
            if (area := registry.async_get_area(area_id))
            else area_id.replace("_", " ").title()
            for area_id in session.area_ids
        )
        prefix = f"sensor.contextual_controls_{terminal_id}"
        items = []
        for index in range(1, MAX_ITEMS + 1):
            detail = self._slot_detail(session, index)
            # Legacy action sensors remain available to older clients.
            self.hass.states.async_set(
                f"{prefix}_action_{index}", detail.get("label", "")[:255], detail
            )
            if session.slots.get(index):
                items.append(detail)
        for key, value in {
            "title": title,
            "status": f"{len(items)} controlli disponibili",
            "mode": session.mode,
            "feedback": session.feedback,
            "revision": str(session.slots.generation),
        }.items():
            self.hass.states.async_set(
                f"{prefix}_{key}",
                value,
                {
                    "terminal": terminal_id,
                    "area_id": session.area_ids[0],
                    "area_ids": list(session.area_ids),
                },
            )
        payload = {
            "schema": 2,
            "terminal_id": terminal_id,
            "title": title,
            "terminal_name": session.profile["terminal_name"] or terminal_id,
            "revision": str(session.slots.generation),
            "area_ids": list(session.area_ids),
            "mode": session.mode,
            "active_slot": session.active_slot,
            "pending_value": session.pending_value,
            "feedback": session.feedback,
            "dim_timeout": session.profile["dim_timeout"],
            "off_timeout": session.profile["off_timeout"],
            "items": items,
        }
        self.hass.states.async_set(
            f"{prefix}_data",
            str(session.slots.generation),
            {
                "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        )

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
            await self._track_adjustment(session, context)
            session.mode, session.active_slot, session.pending_value = "menu", None, None
            session.feedback = "ready"
            await self.async_publish(terminal_id)
            return {"success": True, "mode": "menu"}
        selected = session.active_slot if session.mode == "adjust" else slot
        if selected is None or not 1 <= selected <= MAX_ITEMS:
            return {"success": False, "reason": "invalid_slot"}
        detail = self._slot_detail(session, selected)
        if not detail.get("available") or not detail.get("supported"):
            session.feedback = "unsupported" if not detail.get("supported") else "unavailable"
            await self.async_publish(terminal_id)
            return {"success": False, "reason": session.feedback}
        fixed = detail["source"] == "fixed"
        kwargs = {"fixed": True} if fixed else {}
        if input_name == "select" and session.mode != "adjust":
            await self._emit(session, "select", selected, detail, {"success": True})
            return {"success": True}
        if input_name == "select":
            if detail["domain"] == "climate":
                if session.pending_value is None:
                    return {"success": False, "reason": "invalid_value"}
                detail = {**detail, "value": session.pending_value}
                proposed = session.pending_value + (delta or 0) * detail["step"]
                session.pending_value = round(max(detail["min"], min(detail["max"], proposed)), 3)
                result = {"success": True, "value": session.pending_value, "pending": True}
            else:
                result = await self.coordinator.async_adjust_terminal_slot(
                    detail["entity_id"], delta or 0, context, **kwargs
                )
                if result.get("success"):
                    session.adjusted_action = result.get("action")
            await self._emit(
                session, "preview" if result.get("pending") else "adjust", selected, detail, result
            )
            session.feedback = (
                "adjust" if result.get("success") else str(result.get("reason", "error"))
            )
            await self.async_publish(terminal_id)
            return result
        if session.mode == "adjust" and input_name == "activate":
            result = {"success": True}
            if detail["domain"] == "climate" and session.pending_value is not None:
                result = await self.coordinator.async_adjust_terminal_slot(
                    detail["entity_id"], 0, context, value_override=session.pending_value, **kwargs
                )
                if result.get("success"):
                    session.adjusted_action = result.get("action")
                else:
                    session.feedback = str(result.get("reason", "error"))
                    await self.async_publish(terminal_id)
                    return result
            await self._emit(session, "confirm", selected, detail, result)
            await self._track_adjustment(session, context)
            session.mode, session.active_slot, session.pending_value = "menu", None, None
            session.feedback = "ok"
        elif input_name == "adjust" or (
            input_name == "activate" and detail["kind"] in {"NUMBER", "CLIMATE", "MEDIA"}
        ):
            if detail["kind"] not in {"LIGHT", "NUMBER", "CLIMATE", "MEDIA"}:
                return {"success": False, "reason": "unsupported_action"}
            session.mode, session.active_slot = "adjust", selected
            session.adjusted_action, session.initial_value = None, detail["value"]
            session.pending_value = (
                float(detail["value"]) if detail["domain"] == "climate" else None
            )
            session.feedback = "adjust"
            await self._emit(session, "enter_adjust", selected, detail, {"success": True})
        elif input_name == "activate":
            session.feedback = "loading"
            await self.async_publish(terminal_id)
            result = await self.coordinator.async_execute_terminal_entity(
                detail["entity_id"], selected, context, **kwargs
            )
            await self._emit(session, "activate", selected, detail, result)
            session.feedback = "ok" if result.get("success") else str(result.get("reason", "error"))
            await self.async_publish(terminal_id)
            return result
        else:
            return {"success": False, "reason": "invalid_input"}
        await self.async_publish(terminal_id)
        return {"success": True, "mode": session.mode}

    async def _track_adjustment(self, session: TerminalSession, context: Context) -> None:
        if session.adjusted_action and session.active_slot is not None:
            snapshot = session.slots.get(session.active_slot)
            if snapshot and snapshot.source != "fixed":
                await self.coordinator._async_track_terminal_usage(
                    snapshot.entity_id, session.adjusted_action, session.active_slot, context
                )
        session.adjusted_action = None

    async def _emit(
        self,
        session: TerminalSession,
        input_name: str,
        selected: int,
        detail: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        observed = self.hass.states.get(detail["entity_id"])
        new_value = result.get("value")
        if isinstance(new_value, (int, float)):
            if detail["domain"] == "light":
                new_value = round(new_value * 100 / 255)
            elif detail["domain"] == "media_player":
                new_value = round(new_value * 100)
        elif observed is not None and result.get("success"):
            new_value = self._control_values(detail["domain"], observed.state, observed.attributes)[
                0
            ]
        self.hass.bus.async_fire(
            EVENT_TERMINAL_INPUT,
            {
                "timestamp": dt_util.utcnow().isoformat(),
                "terminal": session.terminal_id,
                "terminal_id": session.terminal_id,
                "area_id": session.area_ids[0],
                "area_ids": list(session.area_ids),
                "input": input_name,
                "slot": selected,
                "position": selected,
                "mode": session.mode,
                "revision": session.slots.generation,
                "action_id": detail["entity_id"],
                "source": detail["source"],
                "previous_value": detail["value"],
                "new_value": new_value,
                "initial_value": session.initial_value if session.mode == "adjust" else None,
                "unit": detail["unit"],
                "previous_state": detail["state"],
                "new_state": observed.state if observed is not None else None,
                "action": result.get("action", input_name),
                "available_action_ids": [s.entity_id for s in session.slots.slots if s],
                "success": bool(result.get("success")),
            },
        )

    def _slot_detail(self, session: TerminalSession, slot: int) -> dict[str, Any]:
        snapshot = session.slots.get(slot)
        if snapshot is None:
            return {"slot": slot, "available": False, "supported": False, "label": ""}
        entity = snapshot.entity_id
        domain = entity.partition(".")[0]
        state = self.hass.states.get(entity)
        attrs = dict(state.attributes) if state else {}
        if domain == "climate" and "temperature_unit" not in attrs:
            units = getattr(getattr(self.hass, "config", None), "units", None)
            attrs["temperature_unit"] = getattr(units, "temperature_unit", "°C")
        raw = state.state if state else "unavailable"
        fixed = snapshot.source == "fixed"
        supported = domain in {
            "light",
            "climate",
            "switch",
            "number",
            "media_player",
            "cover",
            "scene",
            "script",
            "button",
            "input_button",
            "input_boolean",
            "fan",
        }
        if fixed and domain in {"fan"}:
            supported = False  # Display only until an explicit fan adapter is added.
        kind = {
            "climate": "CLIMATE",
            "number": "NUMBER",
            "media_player": "MEDIA",
            "switch": "TOGGLE",
            "input_boolean": "TOGGLE",
        }.get(domain, "ACTION")
        if domain == "light":
            kind = "LIGHT" if self._light_supports_brightness(attrs) else "TOGGLE"
        if domain == "cover" and isinstance(attrs.get("current_position"), int):
            kind = "NUMBER"
        value, minimum, maximum, step, unit = self._control_values(domain, raw, attrs)
        if kind == "CLIMATE" and not isinstance(value, (int, float)):
            supported = False
        icon = attrs.get("icon")
        from homeassistant.helpers import entity_registry as er

        entry = er.async_get(self.hass).async_get(entity)
        if entry and entry.icon:
            icon = entry.icon
        icon = (
            icon
            or default_icon(domain, attrs.get("device_class"))
            or DEFAULT_ICONS.get(domain, "mdi:help-circle")
        )
        name = str(attrs.get("friendly_name", entity))[:160]
        language = getattr(getattr(self.hass, "config", None), "language", "it")
        text = state_text(domain, raw, attrs, language)
        return {
            "slot": slot,
            "id": entity,
            "entity_id": entity,
            "source": "fixed" if fixed else "contextual",
            "domain": domain,
            "name": name,
            "label": name + ": " + self._value_label(domain, raw, attrs),
            "icon": icon,
            "icon_glyph": icon_glyph(icon),
            "kind": kind if supported else "UNSUPPORTED",
            "state": raw,
            "state_text": text,
            "supported": supported,
            "available": state is not None
            and raw != "unavailable"
            and (raw != "unknown" or domain in {"scene", "button", "input_button"}),
            "value": value,
            "min": minimum,
            "max": maximum,
            "step": step,
            "unit": unit,
            "current_temperature": attrs.get("current_temperature"),
            "hvac_action": attrs.get("hvac_action"),
            "score": snapshot.score,
            "rank_reason": snapshot.reason,
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
