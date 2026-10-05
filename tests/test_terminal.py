"""Test the Dial protocol with lightweight HA boundary doubles."""

import asyncio
import importlib
import json
import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def terminal(monkeypatch):
    core = ModuleType("homeassistant.core")
    core.Context = core.HomeAssistant = object
    registry = SimpleNamespace(async_get_area=lambda area: SimpleNamespace(name=area))
    helpers = ModuleType("homeassistant.helpers")
    helpers.area_registry = SimpleNamespace(async_get=lambda hass: registry)
    helpers.entity_registry = SimpleNamespace(
        async_get=lambda hass: SimpleNamespace(async_get=lambda entity: None)
    )
    util = ModuleType("homeassistant.util")
    util.dt = SimpleNamespace(now=lambda: datetime.now(UTC), utcnow=lambda: datetime.now(UTC))
    for name, module in {
        "homeassistant": ModuleType("homeassistant"),
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.util": util,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    name = "custom_components.contextual_controls.terminal"
    monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module(name)
    yield module
    sys.modules.pop(name, None)


@pytest.fixture
def dial(terminal):
    entities = {
        "light.sofa": SimpleNamespace(
            state="off",
            attributes={"friendly_name": "Sofa", "supported_color_modes": ["brightness"]},
        ),
        "switch.dining": SimpleNamespace(state="on", attributes={}),
        "light.kitchen": SimpleNamespace(state="on", attributes={"brightness": 128}),
        "light.bedroom": SimpleNamespace(state="on", attributes={"brightness": 128}),
    }
    published = {}
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=entities.get,
            async_set=lambda key, value, attrs: published.update({key: (value, attrs)}),
        ),
        bus=SimpleNamespace(async_fire=Mock()),
    )
    coordinator = SimpleNamespace(
        options={"terminal_mappings": "dial:living+dining+kitchen", "quick_access_stability": 0},
        areas={
            "light.sofa": "living",
            "switch.dining": "dining",
            "light.kitchen": "kitchen",
            "light.bedroom": "bedroom",
        },
        terminal_rows=[{"entity_id": entity} for entity in entities],
        _quick_target_valid=lambda entity: entity in entities,
        async_adjust_terminal_slot=AsyncMock(return_value={"success": True, "action": "turn_on"}),
        async_execute_terminal_entity=AsyncMock(return_value={"success": True}),
        _async_track_terminal_usage=AsyncMock(),
    )
    manager = terminal.TerminalManager(hass, coordinator)
    asyncio.run(manager.async_configure())
    return manager, coordinator, published


def test_native_multi_area_parser(terminal):
    assert terminal.parse_terminal_mappings(" dial : living + dining + kitchen ") == {
        "dial": ("living", "dining", "kitchen")
    }
    with pytest.raises(ValueError):
        terminal.parse_terminal_mappings("dial:living+living")


def test_projection_filters_before_five_slot_limit(dial):
    manager, _, published = dial
    assert [slot.entity_id for slot in manager.sessions["dial"].slots.slots if slot] == [
        "light.sofa",
        "switch.dining",
        "light.kitchen",
    ]
    assert published["sensor.contextual_controls_dial_action_1"][1]["kind"] == "LIGHT"
    assert published["sensor.contextual_controls_dial_status"][1]["area_ids"] == [
        "living",
        "dining",
        "kitchen",
    ]


def test_light_adjustment_confirms_without_toggling_and_tracks_once(dial):
    manager, coordinator, published = dial

    async def scenario():
        revision = str(manager.sessions["dial"].slots.generation)
        await manager.async_input("dial", "adjust", 1, None, revision, object())
        # A new ranking cannot replace the entity currently being edited.
        coordinator.terminal_rows.reverse()
        await manager.async_publish("dial")
        await manager.async_input("dial", "select", 1, 1, revision, object())
        await manager.async_input("dial", "select", 1, 1, revision, object())
        assert manager.sessions["dial"].mode == "adjust"
        assert published["sensor.contextual_controls_dial_feedback"][0] == "adjust"
        await manager.async_input("dial", "activate", 1, None, revision, object())

    asyncio.run(scenario())
    assert coordinator.async_adjust_terminal_slot.await_count == 2
    assert coordinator.async_adjust_terminal_slot.await_args.args[0] == "light.sofa"
    coordinator.async_execute_terminal_entity.assert_not_awaited()
    coordinator._async_track_terminal_usage.assert_awaited_once()
    assert manager.sessions["dial"].mode == "menu"


def test_native_light_activate_still_toggles_and_stale_input_is_rejected(dial):
    manager, coordinator, _ = dial
    result = asyncio.run(manager.async_input("dial", "activate", 1, None, "old", object()))
    assert result["reason"] == "stale_revision"
    coordinator.async_execute_terminal_entity.assert_not_awaited()
    asyncio.run(manager.async_input("dial", "activate", 1, None, None, object()))
    coordinator.async_execute_terminal_entity.assert_awaited_once()


def test_fixed_items_precede_suggestions_even_outside_assigned_areas(dial):
    manager, coordinator, published = dial
    coordinator.options["terminal_settings"] = {
        "dial": {
            "fixed_entities": ["light.bedroom", "switch.dining", "sensor.missing"],
            "zone_name": "Salotto",
            "terminal_name": "Dial vicino al divano",
        }
    }
    asyncio.run(manager.async_configure())
    payload = json.loads(published["sensor.contextual_controls_dial_data"][1]["payload"])
    assert payload["title"] == "Salotto"
    assert payload["terminal_name"] == "Dial vicino al divano"
    assert [item["id"] for item in payload["items"]] == [
        "light.bedroom",
        "switch.dining",
        "sensor.missing",
        "light.sofa",
        "light.kitchen",
    ]
    assert payload["items"][2]["supported"] is False
    assert payload["items"][2]["state_text"] == "Non disponibile"
    revision = payload["revision"]
    asyncio.run(manager.async_publish("dial"))
    assert (
        json.loads(published["sensor.contextual_controls_dial_data"][1]["payload"])["revision"]
        == revision
    )


def test_disabled_suggestions_unsupported_no_command_and_fixed_no_learning(dial):
    manager, coordinator, published = dial
    coordinator.options["terminal_settings"] = {
        "dial": {
            "fixed_entities": ["light.sofa", "sensor.missing"],
            "contextual_enabled": False,
        }
    }
    asyncio.run(manager.async_configure())
    payload = json.loads(published["sensor.contextual_controls_dial_data"][1]["payload"])
    assert len(payload["items"]) == 2
    result = asyncio.run(manager.async_input("dial", "activate", 2, None, None, object()))
    assert result["reason"] == "unsupported"
    coordinator.async_execute_terminal_entity.assert_not_awaited()

    async def scenario():
        await manager.async_input("dial", "adjust", 1, None, None, object())
        await manager.async_input("dial", "select", 1, 1, None, object())
        await manager.async_input("dial", "activate", 1, None, None, object())

    asyncio.run(scenario())
    assert coordinator.async_adjust_terminal_slot.await_args.kwargs == {"fixed": True}
    coordinator._async_track_terminal_usage.assert_not_awaited()
    event = manager.hass.bus.async_fire.call_args.args[1]
    assert event["source"] == "fixed"
    assert event["terminal_id"] == "dial"
    assert event["position"] == 1
    assert "timestamp" in event


def test_climate_preview_commit_bounds_and_cancel(dial):
    manager, coordinator, _ = dial
    old_get = manager.hass.states.get
    climate = SimpleNamespace(
        state="heat",
        attributes={
            "temperature": 21.5,
            "current_temperature": 20,
            "min_temp": 16,
            "max_temp": 22,
            "target_temp_step": 0.5,
        },
    )
    manager.hass.states.get = lambda entity: (
        climate if entity == "climate.test" else old_get(entity)
    )
    coordinator.options["terminal_settings"] = {
        "dial": {
            "fixed_entities": ["climate.test"],
            "contextual_enabled": False,
        }
    }
    asyncio.run(manager.async_configure())

    async def scenario():
        await manager.async_input("dial", "activate", 1, None, None, object())
        await manager.async_input("dial", "select", 1, 20, None, object())
        assert manager.sessions["dial"].pending_value == 22
        coordinator.async_adjust_terminal_slot.assert_not_awaited()
        await manager.async_input("dial", "back", 1, None, None, object())
        coordinator.async_adjust_terminal_slot.assert_not_awaited()
        await manager.async_input("dial", "activate", 1, None, None, object())
        await manager.async_input("dial", "select", 1, -1, None, object())
        await manager.async_input("dial", "activate", 1, None, None, object())

    asyncio.run(scenario())
    assert coordinator.async_adjust_terminal_slot.await_args.args[:2] == ("climate.test", 0)
    assert coordinator.async_adjust_terminal_slot.await_args.kwargs == {
        "fixed": True,
        "value_override": 21.0,
    }
    coordinator._async_track_terminal_usage.assert_not_awaited()
