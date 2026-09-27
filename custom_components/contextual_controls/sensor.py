"""Expose ranked suggestions and stable cached quick-access slots."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME, VERSION


async def async_setup_entry(hass, entry, async_add_entities):
    entities = [ContextualSensor(entry.runtime_data, entry)]
    if entry.runtime_data.options["quick_access_enabled"]:
        entities.extend(
            QuickAccessSlotSensor(entry.runtime_data, entry, slot)
            for slot in range(1, int(entry.runtime_data.options["quick_access_slots"]) + 1)
        )
    async_add_entities(entities)


class ContextualSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "suggestions"
    _attr_icon = "mdi:gesture-tap-button"
    _unrecorded_attributes = frozenset({"entities", "candidate_scores"})

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_suggestions"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=NAME,
            model=NAME,
            sw_version=VERSION,
        )

    @property
    def native_value(self):
        return len(self.coordinator.data.get("entities", []))

    @property
    def extra_state_attributes(self):
        return self.coordinator.data


class QuickAccessSlotSensor(CoordinatorEntity, SensorEntity):
    """A stable entity whose target follows a coordinator slot snapshot."""

    _attr_has_entity_name = True
    _attr_translation_key = "quick_access_slot"
    _unrecorded_attributes = frozenset(
        {
            "target_entity_id",
            "target_name",
            "target_domain",
            "target_state",
            "target_icon",
            "score",
            "reason",
            "action",
        }
    )

    def __init__(self, coordinator, entry, slot: int) -> None:
        super().__init__(coordinator)
        self._slot = slot
        # This is a deliberately stable public bridge consumed by Shortcuts and
        # Apple Watch wrappers. Let the entity registry resolve a suffix only if
        # another integration instance already owns the canonical id.
        self.entity_id = f"sensor.contextual_control_{slot}"
        self._attr_unique_id = f"{entry.entry_id}_quick_access_{slot}"
        self._attr_translation_placeholders = {"slot": str(slot)}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=NAME,
            model=NAME,
            sw_version=VERSION,
        )

    @property
    def available(self) -> bool:
        return bool(self.coordinator.quick_access_slot(self._slot).get("available"))

    @property
    def native_value(self):
        data = self.coordinator.quick_access_slot(self._slot)
        return data.get("name") if data.get("available") else None

    @property
    def icon(self):
        data = self.coordinator.quick_access_slot(self._slot)
        return data.get("icon") or f"mdi:numeric-{self._slot}-circle"

    @property
    def extra_state_attributes(self):
        data = self.coordinator.quick_access_slot(self._slot)
        return {
            "slot": self._slot,
            "target_entity_id": data.get("entity_id"),
            "target_name": data.get("name"),
            "target_domain": data.get("domain"),
            "target_state": data.get("state"),
            "target_icon": data.get("icon"),
            "score": data.get("score"),
            "reason": data.get("reason"),
            "action": data.get("recommended_action"),
            "available": bool(data.get("available")),
            "slot_generation_id": data.get("slot_generation_id"),
            "last_changed_target": data.get("slot_updated_at"),
        }
