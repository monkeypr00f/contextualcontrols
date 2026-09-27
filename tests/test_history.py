from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.contextual_controls.const import MAX_RECORDS
from custom_components.contextual_controls.history import (
    decode,
    encode,
    migrate_payload,
    reset,
    retain,
)
from custom_components.contextual_controls.models import Usage

NOW = datetime(2026, 9, 24, tzinfo=UTC)


def row(entity="light.a", user="alice", days=1):
    return Usage(
        NOW - timedelta(days=days),
        entity,
        user,
        "manual",
        "turn_on",
        0.9,
        "living",
        True,
        (("sensor.mode", "evening"),),
    )


def test_serialization_preserves_all_fields():
    records = [row(), replace(row(), source="quick_access", source_detail="shortcut")]
    assert decode(encode(records)) == (records, 0)


def test_v1_migration_and_future_rejection():
    data = encode([row()])
    del data["records"][0]["confidence"]
    del data["records"][0]["area_id"]
    migrated, errors = decode(migrate_payload(1, data))
    assert errors == 0 and migrated[0].confidence == 0.2 and migrated[0].area_id is None
    assert migrated[0].source == "manual" and migrated[0].presence_home is None
    with pytest.raises(ValueError):
        migrate_payload(999, data)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("timestamp", "broken"),
        ("timestamp", "2026-01-01T00:00:00"),
        ("confidence", float("nan")),
        ("confidence", 2),
        ("entity_id", "invalid"),
        ("user_id", ["invalid"]),
        ("source", "invented"),
        ("area_id", {}),
        ("presence_home", "yes"),
        ("context_states", ["invalid"]),
    ],
)
def test_invalid_records_skipped(key, value):
    data = encode([row(), row()])
    data["records"][0][key] = value
    records, errors = decode(data)
    assert errors == 1 and len(records) == 1


def test_retention_boundary_future_and_capacity():
    records, evicted = retain([row(days=91), row(days=90), row(days=0), row(days=-1)], NOW)
    assert len(records) == 2 and evicted == 0
    records, evicted = retain([row()] * (MAX_RECORDS + 7), NOW)
    assert len(records) == MAX_RECORDS and evicted == 7


def test_selective_reset_and_full_reset():
    records = [row(), row(user="bob"), row(entity="light.b")]
    assert reset(records, entity_id="light.a") == [records[2]]
    assert reset(records, user_id="alice") == [records[1]]
    assert reset(records, entity_id="light.a", user_id="alice") == records[1:]
    assert not reset(records)
