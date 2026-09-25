"""Expose ranked suggestions; no command execution."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME, VERSION


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ContextualSensor(entry.runtime_data, entry)])


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
