"""Versioned payloads, validation, retention and selective reset."""

import math
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from .const import MAX_RECORDS, RETENTION_DAYS
from .models import Usage

ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def migrate_payload(version: int, data: dict[str, Any]) -> dict[str, Any]:
    if version not in (1, 2, 3, 4):
        raise ValueError("Unsupported storage version")
    if version == 4:
        return data
    rows = data.get("records", [])
    if version == 1:
        rows = [{"area_id": None, "confidence": 0.2, **row} for row in rows]
    source_map = {"user": "manual", "child": "unknown", "unknown": "unknown"}
    return {
        "records": [
            {
                **row,
                "source": source_map.get(row.get("source"), row.get("source", "unknown")),
                "presence_home": None if version < 3 else row.get("presence_home"),
                "context_states": [] if version < 3 else row.get("context_states", []),
                "source_detail": None,
            }
            for row in rows
        ]
    }


def decode(data: dict[str, Any]) -> tuple[list[Usage], int]:
    records: list[Usage] = []
    rejected = 0
    rows = data.get("records", [])
    if not isinstance(rows, list):
        raise ValueError("Invalid records container")
    for row in rows:
        try:
            timestamp = datetime.fromisoformat(row["timestamp"])
            confidence = float(row["confidence"])
            if (
                timestamp.tzinfo is None
                or not ENTITY_ID.fullmatch(row["entity_id"])
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
                or row["source"]
                not in ("manual", "assist", "automation", "script", "unknown", "quick_access")
                or not isinstance(row["action"], str)
                or row.get("user_id") is not None
                and not isinstance(row["user_id"], str)
                or row.get("area_id") is not None
                and not isinstance(row["area_id"], str)
                or row.get("presence_home") is not None
                and not isinstance(row["presence_home"], bool)
                or row.get("source_detail") is not None
                and row.get("source_detail")
                not in (
                    "apple_watch",
                    "ios_lock_screen",
                    "shortcut",
                    "action_button",
                    "control_center",
                    "unknown",
                )
            ):
                raise ValueError("Invalid record")
            context_states = row.get("context_states", [])
            if not isinstance(context_states, list) or any(
                not isinstance(item, list | tuple)
                or len(item) != 2
                or not all(isinstance(value, str) for value in item)
                for item in context_states
            ):
                raise ValueError("Invalid context snapshot")
            records.append(
                Usage(
                    timestamp,
                    row["entity_id"],
                    row.get("user_id"),
                    row["source"],
                    row["action"],
                    confidence,
                    row.get("area_id"),
                    row.get("presence_home"),
                    tuple((item[0], item[1]) for item in context_states),
                    row.get("source_detail"),
                )
            )
        except KeyError, TypeError, ValueError, OverflowError:
            rejected += 1
    return records, rejected


def encode(records: Iterable[Usage]) -> dict[str, Any]:
    return {
        "records": [
            {
                "timestamp": row.timestamp.isoformat(),
                "entity_id": row.entity_id,
                "user_id": row.user_id,
                "source": row.source,
                "action": row.action,
                "confidence": row.confidence,
                "area_id": row.area_id,
                "presence_home": row.presence_home,
                "context_states": [list(item) for item in row.context_states],
                "source_detail": row.source_detail,
            }
            for row in records
        ]
    }


def retain(records: Iterable[Usage], now: datetime) -> tuple[list[Usage], int]:
    minimum = now - timedelta(days=RETENTION_DAYS)
    valid = sorted(
        (row for row in records if minimum <= row.timestamp <= now), key=lambda row: row.timestamp
    )
    dropped = max(0, len(valid) - MAX_RECORDS)
    return valid[-MAX_RECORDS:], dropped


def reset(
    records: Iterable[Usage], entity_id: str | None = None, user_id: str | None = None
) -> list[Usage]:
    return [
        row
        for row in records
        if not (
            (entity_id is None or row.entity_id == entity_id)
            and (user_id is None or row.user_id == user_id)
        )
    ]
