"""Private Home Assistant Store adapter, with immutable write snapshots."""

from collections import deque
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN, MAX_RECORDS, RETENTION_DAYS, STORAGE_VERSION
from .history import decode, encode, migrate_payload, reset, retain
from .models import Usage


class LearningStore(Store):
    async def _async_migrate_func(self, old_major_version, old_minor_version, old_data):
        """Store's supported subclass migration hook."""
        return migrate_payload(old_major_version, old_data)


class History:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.store = LearningStore(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}",
            private=True,
            serialize_in_event_loop=False,
        )
        self.records: deque[Usage] = deque()
        self.rejected = 0
        self.evicted = 0

    async def async_load(self, now: datetime) -> None:
        payload = await self.store.async_load()
        if payload is None:
            return
        rows, self.rejected = await self.hass.async_add_executor_job(decode, payload)
        rows, self.evicted = await self.hass.async_add_executor_job(retain, rows, now)
        self.records = deque(rows)

    @callback
    def prune(self, now: datetime) -> None:
        cutoff = now - timedelta(days=RETENTION_DAYS)
        while self.records and self.records[0].timestamp < cutoff:
            self.records.popleft()
        while len(self.records) > MAX_RECORDS:
            self.records.popleft()
            self.evicted += 1

    @callback
    def append(self, record: Usage) -> None:
        self.records.append(record)
        self.prune(record.timestamp)
        self.schedule_save()

    @callback
    def schedule_save(self) -> None:
        # The executor sees only this immutable tuple, never the live deque.
        snapshot = tuple(self.records)
        self.store.async_delay_save(lambda: encode(snapshot), 15)

    async def async_flush(self) -> None:
        snapshot = tuple(self.records)
        payload = await self.hass.async_add_executor_job(encode, snapshot)
        await self.store.async_save(payload)
        # Ingestion may continue while a reset flush serializes/writes. Ensure
        # a newer delayed snapshot is not overwritten by the older flush.
        if tuple(self.records) != snapshot:
            self.schedule_save()

    async def async_reset(self, entity_id: str | None, user_id: str | None) -> None:
        # Mutation has no await, so concurrent service ingestion cannot be lost.
        self.records = deque(reset(self.records, entity_id, user_id))
        await self.async_flush()

    def counts(self) -> dict[str, Any]:
        return {
            "learning_records_count": len(self.records),
            "rejected_records": self.rejected,
            "capacity_evictions": self.evicted,
        }
