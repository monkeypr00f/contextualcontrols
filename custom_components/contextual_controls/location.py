"""Deterministic indoor location context derived from Wi-Fi access points."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

INVALID_STATES = {"unknown", "unavailable"}


@dataclass(frozen=True, slots=True)
class LocationZone:
    """One functional location context configured by the user."""

    context_id: str
    name: str
    access_points: tuple[str, ...] = ()
    area_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TrackerObservation:
    """Minimal public state extracted from a configured device tracker."""

    entity_id: str
    state: str
    connected_to: str | None


@dataclass(frozen=True, slots=True)
class LocationSnapshot:
    """Stable state consumed by ranking, sensors and diagnostics."""

    home: bool | None = None
    location_context: str | None = None
    connected_to: str | None = None
    source: str | None = None
    confidence: float = 0.0
    tracker_entity_id: str | None = None
    last_connected_to: str | None = None
    last_location_context: str | None = None
    last_changed: datetime | None = None
    pending_context: str | None = None
    pending_since: datetime | None = None


def normalize_zones(rows: Iterable[dict[str, Any]]) -> tuple[LocationZone, ...]:
    """Validate and normalize config-entry-safe zone dictionaries."""
    zones: list[LocationZone] = []
    seen_ids: set[str] = set()
    claimed_access_points: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        context_id = str(row.get("id", "")).strip().lower()
        if not context_id or context_id in seen_ids:
            continue
        access_points = []
        for value in row.get("access_points", []):
            access_point = str(value).strip()
            key = access_point.casefold()
            if access_point and key not in claimed_access_points:
                access_points.append(access_point)
                claimed_access_points.add(key)
        zones.append(
            LocationZone(
                context_id=context_id,
                name=str(row.get("name") or context_id).strip(),
                access_points=tuple(access_points),
                area_ids=tuple(dict.fromkeys(str(value) for value in row.get("areas", []))),
                entity_ids=tuple(dict.fromkeys(str(value) for value in row.get("entities", []))),
            )
        )
        seen_ids.add(context_id)
    return tuple(zones)


def zones_to_options(zones: Iterable[LocationZone]) -> list[dict[str, Any]]:
    """Return JSON-safe data for ConfigEntry.options."""
    return [
        {
            "id": zone.context_id,
            "name": zone.name,
            "access_points": list(zone.access_points),
            "areas": list(zone.area_ids),
            "entities": list(zone.entity_ids),
        }
        for zone in zones
    ]


class LocationEngine:
    """Resolve and debounce functional contexts; never polls Home Assistant."""

    def __init__(self, observed_access_points: Iterable[str] = ()) -> None:
        self.observed_access_points = {
            value.strip()
            for value in observed_access_points
            if isinstance(value, str) and value.strip()
        }
        self.zones: tuple[LocationZone, ...] = ()
        self._access_point_map: dict[str, LocationZone] = {}
        self.snapshot = LocationSnapshot()
        self._pending_connected_to: str | None = None
        self._pending_tracker: str | None = None

    def configure(self, rows: Iterable[dict[str, Any]]) -> None:
        self.zones = normalize_zones(rows)
        self._access_point_map = {
            access_point.casefold(): zone
            for zone in self.zones
            for access_point in zone.access_points
        }

    def zone(self, context_id: str | None) -> LocationZone | None:
        return next((zone for zone in self.zones if zone.context_id == context_id), None)

    def context_for_access_point(self, access_point: str | None) -> str:
        if not access_point:
            return "unknown"
        zone = self._access_point_map.get(access_point.strip().casefold())
        return zone.context_id if zone else "unknown"

    @property
    def unassigned_access_points(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                value
                for value in self.observed_access_points
                if value.casefold() not in self._access_point_map
            )
        )

    def _commit(
        self,
        *,
        context_id: str | None,
        connected_to: str | None,
        home: bool | None,
        source: str | None,
        confidence: float,
        tracker: str | None,
        now: datetime,
    ) -> None:
        previous = self.snapshot.location_context
        changed = previous != context_id
        self.snapshot = LocationSnapshot(
            home=home,
            location_context=context_id,
            connected_to=connected_to,
            source=source,
            confidence=confidence,
            tracker_entity_id=tracker,
            last_connected_to=(
                connected_to or self.snapshot.connected_to or self.snapshot.last_connected_to
            ),
            last_location_context=previous if changed else self.snapshot.last_location_context,
            last_changed=(
                now if changed or self.snapshot.last_changed is None else self.snapshot.last_changed
            ),
        )
        self._pending_connected_to = None
        self._pending_tracker = None

    def observe(
        self,
        observations: Iterable[TrackerObservation],
        now: datetime,
        debounce_seconds: int,
    ) -> float | None:
        """Observe tracker states and return seconds until a pending commit."""
        rows = tuple(observations)
        if not rows:
            self.snapshot = LocationSnapshot()
            self._pending_connected_to = None
            self._pending_tracker = None
            return None

        usable = [row for row in rows if row.state not in INVALID_STATES]
        home_rows = [row for row in usable if row.state == "home"]
        selected = next((row for row in home_rows if row.connected_to), None)
        selected = selected or (home_rows[0] if home_rows else None)

        if selected is None:
            if usable and all(row.state != "home" for row in usable):
                self._commit(
                    context_id="away",
                    connected_to=None,
                    home=False,
                    source="device_tracker",
                    confidence=1.0,
                    tracker=usable[0].entity_id,
                    now=now,
                )
            elif self.snapshot.location_context is not None:
                self.snapshot = replace(
                    self.snapshot,
                    confidence=min(self.snapshot.confidence, 0.2),
                    pending_context=None,
                    pending_since=None,
                )
                self._pending_connected_to = None
                self._pending_tracker = None
            return None

        access_point = selected.connected_to.strip() if selected.connected_to else None
        if access_point:
            self.observed_access_points.add(access_point)
        target = self.context_for_access_point(access_point)
        confidence = 0.75 if target != "unknown" else 0.3 if access_point else 0.2

        if self.snapshot.location_context is None:
            self._commit(
                context_id=target,
                connected_to=access_point,
                home=True,
                source="wifi_ap",
                confidence=confidence,
                tracker=selected.entity_id,
                now=now,
            )
            return None

        if target == self.snapshot.location_context:
            self.snapshot = LocationSnapshot(
                home=True,
                location_context=target,
                connected_to=access_point,
                source="wifi_ap",
                confidence=confidence,
                tracker_entity_id=selected.entity_id,
                last_connected_to=access_point or self.snapshot.last_connected_to,
                last_location_context=self.snapshot.last_location_context,
                last_changed=self.snapshot.last_changed,
            )
            self._pending_connected_to = None
            self._pending_tracker = None
            return None

        pending_since = self.snapshot.pending_since
        if self.snapshot.pending_context != target:
            pending_since = now
            self._pending_connected_to = access_point
            self._pending_tracker = selected.entity_id
        elapsed = max(0.0, (now - pending_since).total_seconds()) if pending_since else 0.0
        remaining = max(0.0, float(debounce_seconds) - elapsed)
        if remaining <= 0:
            self._commit(
                context_id=target,
                connected_to=self._pending_connected_to or access_point,
                home=True,
                source="wifi_ap",
                confidence=confidence,
                tracker=self._pending_tracker or selected.entity_id,
                now=now,
            )
            return None
        self.snapshot = LocationSnapshot(
            home=self.snapshot.home,
            location_context=self.snapshot.location_context,
            connected_to=self.snapshot.connected_to,
            source=self.snapshot.source,
            confidence=self.snapshot.confidence,
            tracker_entity_id=self.snapshot.tracker_entity_id,
            last_connected_to=self.snapshot.last_connected_to,
            last_location_context=self.snapshot.last_location_context,
            last_changed=self.snapshot.last_changed,
            pending_context=target,
            pending_since=pending_since,
        )
        return remaining
