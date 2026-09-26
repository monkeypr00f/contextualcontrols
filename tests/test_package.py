"""Repository contracts and translation coverage for shipped UI fields."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "contextual_controls"


def load(path):
    return json.loads(path.read_text())


def paths(value, prefix=""):
    if isinstance(value, dict):
        return {child for key, item in value.items() for child in paths(item, f"{prefix}.{key}")}
    return {prefix}


def test_translation_keys_match_and_english_is_canonical():
    english = load(COMPONENT / "translations/en.json")
    italian = load(COMPONENT / "translations/it.json")
    assert english == load(COMPONENT / "strings.json")
    assert paths(english) == paths(italian)


def test_hacs_structure_and_local_requirements():
    assert [
        path.name
        for path in (ROOT / "custom_components").iterdir()
        if path.is_dir() and not path.name.startswith("_")
    ] == ["contextual_controls"]
    manifest = load(COMPONENT / "manifest.json")
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []
    assert manifest["iot_class"] == "calculated"
    assert "after_dependencies" not in manifest
    assert not (COMPONENT / "frontend.py").exists()
    assert load(ROOT / "hacs.json")["homeassistant"] == "2026.9.3"
    assert (ROOT / "LICENSE").exists()
    from custom_components.contextual_controls.const import DEFAULTS, VERSION

    assert manifest["version"] == VERSION == "0.5.0"
    assert DEFAULTS["ai_provider"] == "disabled"
    assert DEFAULTS["ai_share_exact_timestamps"] is False
    assert DEFAULTS["ai_share_presence_information"] is False
    assert "openai_api_key" not in DEFAULTS


def test_reasons_are_translated():
    translation = load(COMPONENT / "translations/it.json")
    reasons = translation["entity"]["sensor"]["suggestions"]["state_attributes"]["reason"]["state"]
    assert set(reasons) == {
        "habit",
        "pinned",
        "recent",
        "frequent",
        "domain_default",
        "weekday_habit",
        "presence_habit",
        "context_habit",
        "area_habit",
        "ai_selected",
    }


def test_reset_has_translated_confirmation_and_errors():
    strings = load(COMPONENT / "strings.json")
    assert "confirm" in strings["services"]["reset_learning"]["fields"]
    assert "confirmation_required" in strings["exceptions"]
    assert "confirmation_required" in strings["options"]["error"]
