from datetime import UTC, datetime, timedelta

from custom_components.contextual_controls.quick_access import (
    SlotManager,
    resolve_default_action,
    safety_rejection,
)

NOW = datetime(2026, 9, 26, 8, 10, tzinfo=UTC)


def rows(*entities):
    return [
        {
            "entity_id": entity,
            "score": 1 - index / 10,
            "reason": "test",
            "source": "statistical",
            "pinned": False,
        }
        for index, entity in enumerate(entities)
    ]


def test_slot_mapping_empty_and_generation():
    manager = SlotManager(4, 120)
    assert manager.get(1) is None and manager.get(5) is None
    assert manager.update(rows("light.a", "switch.b"), NOW, lambda _entity: True)
    assert [item.entity_id if item else None for item in manager.slots] == [
        "light.a",
        "switch.b",
        None,
        None,
    ]
    assert manager.generation == 1 and manager.updated_at == NOW
    assert not manager.update(rows("light.a", "switch.b"), NOW, lambda _entity: True)


def test_stability_window_and_expiry():
    manager = SlotManager(2, 120)
    manager.update(rows("light.a", "switch.b"), NOW, lambda _entity: True)
    manager.update(
        rows("cover.garage", "light.entry"),
        NOW + timedelta(seconds=30),
        lambda _entity: True,
    )
    assert [item.entity_id for item in manager.slots if item] == ["light.a", "switch.b"]
    manager.update(
        rows("cover.garage", "light.entry"),
        NOW + timedelta(seconds=121),
        lambda _entity: True,
    )
    assert [item.entity_id for item in manager.slots if item] == [
        "cover.garage",
        "light.entry",
    ]


def test_invalid_target_is_replaced_inside_stability_window():
    manager = SlotManager(2, 120)
    manager.update(rows("light.a", "switch.b"), NOW, lambda _entity: True)
    manager.update(
        rows("cover.garage", "light.entry"),
        NOW + timedelta(seconds=10),
        lambda entity: entity != "light.a",
    )
    assert manager.get(1).entity_id == "cover.garage"
    assert manager.get(2).entity_id == "switch.b"


def test_default_action_resolution():
    for entity in ("light.a", "switch.a", "input_boolean.a", "fan.a"):
        assert resolve_default_action(entity, "off").name == "toggle"
    assert resolve_default_action("scene.evening", "unknown").name == "turn_on"
    assert resolve_default_action("script.bedtime", "off").name == "turn_on"
    assert resolve_default_action("button.gate", "unknown").name == "press"
    assert resolve_default_action("input_button.gate", "unknown").name == "press"
    assert resolve_default_action("cover.gate", "closed").name == "open_cover"
    assert resolve_default_action("cover.gate", "open").name == "close_cover"
    assert resolve_default_action("cover.gate", "opening") is None
    assert resolve_default_action("media_player.tv", "playing", 4, 4).name == "media_play_pause"
    assert resolve_default_action("media_player.tv", "idle", 0, 4) is None


def test_cautious_domains_have_no_invented_action():
    for entity in (
        "climate.home",
        "lock.front_door",
        "alarm_control_panel.home",
        "siren.home",
        "vacuum.home",
    ):
        assert resolve_default_action(entity, "off") is None


def test_safety_modes_and_sensitive_entities():
    assert safety_rejection("light.a", "safe", (), False) is None
    assert safety_rejection("cover.garage", "safe", ("cover.garage",), False)
    assert safety_rejection("cover.garage", "balanced", ("cover.garage",), False)
    assert safety_rejection("cover.garage", "direct", ("cover.garage",), True) is None
    assert safety_rejection("lock.front", "balanced", (), True) == "requires_confirmation"
    assert safety_rejection("lock.front", "direct", (), True) is None
