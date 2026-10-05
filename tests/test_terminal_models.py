"""Configurable terminal limits, presentation and icon projection."""

import pytest

from custom_components.contextual_controls.terminal_icons import default_icon, icon_glyph
from custom_components.contextual_controls.terminal_models import (
    compose_items,
    normalize_profile,
    state_text,
)


def test_fixed_order_deduplicates_contextual_and_caps_total():
    fixed = [f"light.fixed_{i}" for i in range(18)]
    dynamic = [fixed[1], "scene.night", "switch.extra", "button.third"]
    items = compose_items(fixed, dynamic, 12)
    assert items[:18] == [(entity, "fixed") for entity in fixed]
    assert items[18:] == [("scene.night", "contextual"), ("switch.extra", "contextual")]
    assert compose_items(fixed, dynamic, 0) == items[:18]


def test_profiles_allow_every_entity_domain_and_preserve_order():
    profile = normalize_profile({"fixed_entities": ["sensor.a", "lock.b", "sensor.a"]})
    assert profile["fixed_entities"] == ["sensor.a", "lock.b"]
    assert profile["dim_timeout"] == 30
    assert profile["off_timeout"] == 120


@pytest.mark.parametrize(
    "values",
    [
        {"fixed_entities": ["invalid"]},
        {"fixed_entities": [f"sensor.x{i}" for i in range(21)]},
        {"off_timeout": 30},
        {"dim_timeout": 4},
        {"contextual_max_items": 13},
    ],
)
def test_invalid_profiles_fail_safely(values):
    with pytest.raises(ValueError):
        normalize_profile(values)


def test_human_readable_states():
    assert state_text("light", "on", {"brightness": 166}) == "Accesa · 65%"
    assert state_text("light", "off", {"brightness": 166}) == "Spenta"
    assert state_text("switch", "on", {}) == "Acceso"
    assert state_text("switch", "off", {}, "en") == "Off"
    assert "21.5 °C" in state_text(
        "climate",
        "heat",
        {
            "current_temperature": 20,
            "temperature": 21.5,
            "hvac_action": "heating",
        },
    )
    assert state_text("sensor", "unavailable", {}) == "Non disponibile"


def test_actual_mdi_glyphs_and_unknown_icon_fallback():
    assert icon_glyph("mdi:ceiling-light") != icon_glyph("mdi:thermostat")
    assert icon_glyph("custom:unknown") == icon_glyph("mdi:help-circle")
    assert default_icon("sensor", "temperature") == "mdi:thermometer"
