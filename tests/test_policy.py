from copy import deepcopy

import pytest

from custom_components.contextual_controls.const import DEFAULTS
from custom_components.contextual_controls.eligibility import available, compose, eligible
from custom_components.contextual_controls.models import Candidate, Ranked
from custom_components.contextual_controls.tracking import Deduplicator, classify, supports_action


@pytest.fixture
def options():
    return deepcopy(DEFAULTS)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("excluded_entities", "light.test"),
        ("excluded_domains", "light"),
        ("excluded_areas", "bedroom"),
    ],
)
def test_exclusions_override_all_inclusions_and_pins(options, key, value):
    options["included_entities"] = options["pinned_entities"] = ["light.test"]
    options[key] = [value]
    candidate = Candidate("light.test", "on", "bedroom")
    assert not eligible(candidate, options)
    assert compose([Ranked("light.test", 0.9, "habit")], {"light.test": candidate}, options) == []


def test_areas_and_disabled(options):
    options.update(all_areas=False, included_areas=["living"])
    assert eligible(Candidate("light.a", "off", "living"), options)
    assert not eligible(Candidate("light.a", "off", None), options)
    assert not eligible(Candidate("light.a", "off", "living", True), options)


def test_locks_explicit_and_unsupported_safety(options):
    options["included_domains"] += ["lock", "siren", "alarm_control_panel"]
    assert not eligible(Candidate("lock.door", "locked"), options)
    options["included_entities"] = ["lock.door", "siren.a", "alarm_control_panel.a"]
    assert eligible(Candidate("lock.door", "locked"), options)
    assert not eligible(Candidate("siren.a", "off"), options)
    assert not eligible(Candidate("alarm_control_panel.a", "disarmed"), options)


@pytest.mark.parametrize(
    ("slots", "position", "expected"),
    [
        (True, "before", ["light.pin", "light.a"]),
        (False, "after", ["light.a", "light.b", "light.pin"]),
        (False, "before", ["light.pin", "light.a", "light.b"]),
    ],
)
def test_pinned_slots_and_no_duplicates(options, slots, position, expected):
    options.update(
        suggestion_count=2,
        pinned_entities=["light.pin", "light.pin"],
        pinned_use_slots=slots,
        pinned_position=position,
    )
    entities = ["light.pin", "light.a", "light.b"]
    candidates = {key: Candidate(key, "on") for key in entities}
    ranked = [Ranked(key, 0.9, "habit") for key in entities]
    result = compose(ranked, candidates, options)
    assert [row.entity_id for row in result] == expected
    assert sum(row.pinned for row in result) == 1


def test_pins_truncated_and_unavailable_hidden(options):
    options.update(suggestion_count=1, pinned_entities=["light.a", "light.b"])
    candidates = {key: Candidate(key, "on") for key in options["pinned_entities"]}
    assert len(compose([], candidates, options)) == 1
    candidates["light.a"] = Candidate("light.a", "unavailable")
    assert compose([], candidates, options)[0].entity_id == "light.b"
    assert available(Candidate("scene.evening", "unknown"))
    assert not available(Candidate("light.a", "unknown"))


def test_classifier_never_assumes_parent_means_manual():
    assert classify("alice", None) == ("user", 0.9)
    assert classify("alice", "parent") == ("child", 0.3)
    assert classify(None, None) == ("unknown", 0.2)


def test_service_filter():
    assert supports_action("light.a", "light", "turn_on")
    assert supports_action("scene.a", "scene", "turn_on")
    assert not supports_action("scene.a", "scene", "create")
    assert not supports_action("light.a", "switch", "turn_on")
    assert not supports_action("light.a", "homeassistant", "reload_all")


def test_dedup_context_action_and_expiry():
    dedup = Deduplicator()
    assert dedup.accept("ctx", "light.a", "turn_on", 0)
    assert not dedup.accept("ctx", "light.a", "turn_on", 1)
    assert dedup.accept("ctx", "light.a", "turn_off", 2)
    assert dedup.accept("ctx2", "light.a", "turn_on", 3)
    assert dedup.accept("ctx", "light.a", "turn_on", 6)
