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
    if version not in (1, 2):
        raise ValueError("Unsupported storage version")
    if version == 2:
        return data
    return {
        "records": [{"area_id": None, "confidence": 0.2, **row} for row in data.get("records", [])]
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
                or row["source"] not in ("user", "child", "unknown")
                or not isinstance(row["action"], str)
                or row.get("user_id") is not None
                and not isinstance(row["user_id"], str)
                or row.get("area_id") is not None
                and not isinstance(row["area_id"], str)
            ):
                raise ValueError("Invalid record")
            records.append(
                Usage(
                    timestamp,
                    row["entity_id"],
                    row.get("user_id"),
                    row["source"],
                    row["action"],
                    confidence,
                    row.get("area_id"),
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
