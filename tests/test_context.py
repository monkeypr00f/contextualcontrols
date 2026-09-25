from custom_components.contextual_controls.context import (
    context_similarity,
    presence_status,
    snapshot_context,
)


def test_presence_supports_people_trackers_and_binary_sensors():
    states = {"person.alice": "not_home", "binary_sensor.office": "on"}
    assert presence_status(states, ("person.alice", "binary_sensor.office")) is True
    assert presence_status({"person.alice": "not_home"}, ("person.alice",)) is False
    assert presence_status({}, ()) is None
    assert presence_status({"person.alice": "unavailable"}, ("person.alice",)) is None


def test_context_snapshot_is_bounded_to_configured_valid_states():
    states = {"sensor.mode": "evening", "sensor.secret": "x", "sensor.bad": "unknown"}
    assert snapshot_context(states, ("sensor.mode", "sensor.bad")) == (("sensor.mode", "evening"),)


def test_context_similarity_is_neutral_without_overlap():
    current = (("input_boolean.sleep", "on"),)
    assert context_similarity(current, ()) == 1
    assert context_similarity(current, current) > 1
    assert context_similarity(current, (("input_boolean.sleep", "off"),)) < 1
