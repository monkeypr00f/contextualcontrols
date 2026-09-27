"""Pure quick-access slot snapshots, action resolution and safety policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

SECURITY_DOMAINS = frozenset({"lock", "alarm_control_panel", "siren"})
QUICK_ACCESS_SOURCES = frozenset(
    {"apple_watch", "ios_lock_screen", "shortcut", "action_button", "control_center", "unknown"}
)
DEFAULT_ICONS = {
    "light": "mdi:lightbulb",
    "switch": "mdi:toggle-switch",
    "input_boolean": "mdi:toggle-switch",
    "fan": "mdi:fan",
    "scene": "mdi:palette",
    "script": "mdi:script-text",
    "button": "mdi:gesture-tap-button",
    "input_button": "mdi:gesture-tap-button",
    "cover": "mdi:window-shutter",
    "media_player": "mdi:cast",
    "climate": "mdi:thermostat",
    "lock": "mdi:lock",
    "alarm_control_panel": "mdi:shield-home",
    "siren": "mdi:alarm-light",
    "vacuum": "mdi:robot-vacuum",
}


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    """A public Home Assistant action selected without semantic guessing."""

    domain: str
    service: str

    @property
    def name(self) -> str:
        return self.service


@dataclass(frozen=True, slots=True)
class SlotSnapshot:
    """A target held stable independently from later ranking changes."""

    slot: int
    entity_id: str
    score: float
    reason: str
    source: str
    pinned: bool
    changed_at: datetime


def resolve_default_action(
    entity_id: str,
    state: str,
    supported_features: int = 0,
    media_play_pause_mask: int = 0,
) -> ResolvedAction | None:
    """Resolve only actions whose meaning is safe and predictable."""
    domain = entity_id.partition(".")[0]
    if domain in {"light", "switch", "input_boolean", "fan"}:
        return ResolvedAction(domain, "toggle")
    if domain in {"scene", "script"}:
        return ResolvedAction(domain, "turn_on")
    if domain in {"button", "input_button"}:
        return ResolvedAction(domain, "press")
    if domain == "cover":
        if state == "closed":
            return ResolvedAction(domain, "open_cover")
        if state == "open":
            return ResolvedAction(domain, "close_cover")
        return None
    if (
        domain == "media_player"
        and media_play_pause_mask
        and supported_features & media_play_pause_mask
    ):
        return ResolvedAction(domain, "media_play_pause")
    return None


def safety_rejection(
    entity_id: str,
    safety_mode: str,
    sensitive_entities: Sequence[str],
    confirmed: bool,
) -> str | None:
    """Return a safe failure reason, or None when direct execution is allowed."""
    domain = entity_id.partition(".")[0]
    sensitive = entity_id in sensitive_entities or domain in SECURITY_DOMAINS
    if not sensitive:
        return None
    if safety_mode in {"safe", "balanced"} and domain in SECURITY_DOMAINS:
        return "requires_confirmation"
    if safety_mode == "safe" or not confirmed:
        return "requires_confirmation"
    return None


class SlotManager:
    """Map an existing ranked result to sticky, versioned quick-access slots."""

    def __init__(self, count: int, stability_seconds: int) -> None:
        self.count = count
        self.stability = timedelta(seconds=stability_seconds)
        self.generation = 0
        self.updated_at: datetime | None = None
        self.last_refresh: datetime | None = None
        self._slots: list[SlotSnapshot | None] = [None] * count

    @property
    def slots(self) -> tuple[SlotSnapshot | None, ...]:
        return tuple(self._slots)

    def get(self, slot: int) -> SlotSnapshot | None:
        if not 1 <= slot <= self.count:
            return None
        return self._slots[slot - 1]

    def clear(self, now: datetime) -> None:
        if any(self._slots):
            self._slots = [None] * self.count
            self.generation += 1
            self.updated_at = now

    def update(
        self,
        rows: Sequence[Mapping[str, Any]],
        now: datetime,
        is_valid: Callable[[str], bool],
    ) -> bool:
        """Publish ranked rows while preserving still-valid recent targets."""
        self.last_refresh = now
        ranked_rows: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            entity_id = str(row.get("entity_id", ""))
            if entity_id and entity_id not in seen and is_valid(entity_id):
                seen.add(entity_id)
                ranked_rows.append(row)

        previous = list(self._slots)
        next_slots: list[SlotSnapshot | None] = [None] * self.count
        used: set[str] = set()
        row_by_entity = {str(row["entity_id"]): row for row in ranked_rows}

        for index, current in enumerate(previous):
            if current is None or not is_valid(current.entity_id):
                continue
            desired = ranked_rows[index] if index < len(ranked_rows) else None
            same_target = desired is not None and desired["entity_id"] == current.entity_id
            stable = now - current.changed_at < self.stability
            if same_target or stable:
                current_row = row_by_entity.get(current.entity_id)
                next_slots[index] = self._from_row(index + 1, current_row, current, now)
                used.add(current.entity_id)

        for index in range(self.count):
            if next_slots[index] is not None:
                continue
            preferred = ranked_rows[index] if index < len(ranked_rows) else None
            choices = ([preferred] if preferred is not None else []) + list(ranked_rows)
            selected_row: Mapping[str, Any] | None = None
            for item in choices:
                if str(item["entity_id"]) not in used:
                    selected_row = item
                    break
            if selected_row is not None:
                entity_id = str(selected_row["entity_id"])
                next_slots[index] = self._from_row(index + 1, selected_row, None, now)
                used.add(entity_id)

        changed = [item.entity_id if item else None for item in previous] != [
            item.entity_id if item else None for item in next_slots
        ]
        self._slots = next_slots
        if changed:
            self.generation += 1
            self.updated_at = now
        return changed

    @staticmethod
    def _from_row(
        slot: int,
        row: Mapping[str, Any] | None,
        current: SlotSnapshot | None,
        now: datetime,
    ) -> SlotSnapshot:
        if row is None:
            assert current is not None
            return replace(current, slot=slot)
        entity_id = str(row["entity_id"])
        changed_at = current.changed_at if current and current.entity_id == entity_id else now
        return SlotSnapshot(
            slot=slot,
            entity_id=entity_id,
            score=float(row.get("score", 0)),
            reason=str(row.get("reason", "")),
            source=str(row.get("source", "statistical")),
            pinned=bool(row.get("pinned", False)),
            changed_at=changed_at,
        )
