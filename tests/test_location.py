"""Pure tests for Wi-Fi access-point location resolution and stabilization."""

from datetime import UTC, datetime, timedelta

from custom_components.contextual_controls.location import (
    LocationEngine,
    TrackerObservation,
    normalize_zones,
)

NOW = datetime(2026, 9, 30, 7, 20, tzinfo=UTC)
ZONES = [
    {
        "id": "zona_giorno",
        "name": "Zona giorno",
        "access_points": ["fritz-cucina", "fritzbox-master"],
        "areas": ["cucina", "soggiorno"],
        "entities": ["switch.coffee"],
    },
    {
        "id": "zona_notte",
        "name": "Zona notte",
        "access_points": ["fritz-camere"],
        "areas": ["camera"],
        "entities": [],
    },
]


def observation(access_point, state="home"):
    return [TrackerObservation("device_tracker.iphone", state, access_point)]


def engine():
    value = LocationEngine()
    value.configure(ZONES)
    return value


def test_many_access_points_map_to_one_functional_context():
    value = engine()
    assert value.context_for_access_point("fritz-cucina") == "zona_giorno"
    assert value.context_for_access_point("FRITZBOX-MASTER") == "zona_giorno"
    assert value.zone("zona_giorno").area_ids == ("cucina", "soggiorno")


def test_roaming_inside_same_context_does_not_change_context():
    value = engine()
    value.observe(observation("fritz-cucina"), NOW, 15)
    changed_at = value.snapshot.last_changed
    value.observe(observation("fritzbox-master"), NOW + timedelta(seconds=2), 15)
    assert value.snapshot.location_context == "zona_giorno"
    assert value.snapshot.connected_to == "fritzbox-master"
    assert value.snapshot.last_location_context is None
    assert value.snapshot.last_changed == changed_at
    assert value.snapshot.pending_context is None


def test_different_context_requires_minimum_dwell_time():
    value = engine()
    value.observe(observation("fritz-cucina"), NOW, 15)
    remaining = value.observe(observation("fritz-camere"), NOW + timedelta(seconds=1), 15)
    assert remaining == 15
    assert value.snapshot.location_context == "zona_giorno"
    assert value.snapshot.pending_context == "zona_notte"
    remaining = value.observe(observation("fritz-camere"), NOW + timedelta(seconds=17), 15)
    assert remaining is None
    assert value.snapshot.location_context == "zona_notte"
    assert value.snapshot.last_location_context == "zona_giorno"


def test_unmapped_access_point_is_observed_and_reported():
    value = engine()
    value.observe(observation("fritz-nuovo"), NOW, 15)
    assert value.snapshot.location_context == "unknown"
    assert value.snapshot.confidence == 0.3
    assert value.unassigned_access_points == ("fritz-nuovo",)


def test_home_to_away_is_immediate_and_clears_access_point():
    value = engine()
    value.observe(observation("fritz-cucina"), NOW, 15)
    value.observe(observation(None, "not_home"), NOW + timedelta(seconds=1), 15)
    assert value.snapshot.home is False
    assert value.snapshot.location_context == "away"
    assert value.snapshot.connected_to is None
    assert value.snapshot.last_connected_to == "fritz-cucina"
    assert value.snapshot.source == "device_tracker"
    assert value.snapshot.last_location_context == "zona_giorno"


def test_unavailable_tracker_keeps_last_stable_location_with_low_confidence():
    value = engine()
    value.observe(observation("fritz-cucina"), NOW, 15)
    value.observe(observation(None, "unavailable"), NOW + timedelta(seconds=1), 15)
    assert value.snapshot.location_context == "zona_giorno"
    assert value.snapshot.confidence == 0.2


def test_unavailable_tracker_cancels_pending_roam_dwell():
    value = engine()
    value.observe(observation("fritz-cucina"), NOW, 15)
    value.observe(observation("fritz-camere"), NOW + timedelta(seconds=1), 15)
    value.observe(observation(None, "unavailable"), NOW + timedelta(seconds=2), 15)
    assert value.snapshot.pending_context is None
    remaining = value.observe(observation("fritz-camere"), NOW + timedelta(seconds=30), 15)
    assert remaining == 15
    assert value.snapshot.location_context == "zona_giorno"


def test_first_zone_claims_duplicate_access_point():
    zones = normalize_zones(
        ZONES
        + [
            {
                "id": "duplicata",
                "name": "Duplicata",
                "access_points": ["fritz-cucina"],
            }
        ]
    )
    assert zones[-1].access_points == ()
