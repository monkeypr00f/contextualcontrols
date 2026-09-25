"""Real-core smoke test. Runs inside an existing HA container, in a temp config.

Does not connect to the running HA process or command real devices.
Run: python -m unittest tests.runtime_check -v
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from homeassistant import config_entries, loader
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry, device_registry, entity_registry
from homeassistant.setup import async_setup_component

from custom_components.contextual_controls.const import DOMAIN


class RuntimeCheck(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "custom_components",
            Path(self.tmp.name) / "custom_components",
        )
        self.hass = HomeAssistant(self.tmp.name)
        self.hass.config.time_zone = "Europe/Rome"
        self.hass.config.language = "it"
        loader.async_setup(self.hass)
        self.hass.config_entries = config_entries.ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        device_registry.async_setup(self.hass)
        await device_registry.async_load(self.hass)
        await entity_registry.async_load(self.hass)
        await area_registry.async_load(self.hass)
        self.assertTrue(await async_setup_component(self.hass, "homeassistant", {}))
        self.hass.states.async_set("light.test_contextual", "off")
        self.hass.states.async_set("light.excluded_contextual", "off")
        self.hass.states.async_set("scene.pin_contextual", "unknown")
        self.calls = []

        async def dummy(call):
            self.calls.append(call)

        self.hass.services.async_register("light", "turn_on", dummy)

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)
        await self.hass.async_block_till_done()
        self.tmp.cleanup()

    async def test_complete_lifecycle(self):
        from custom_components.contextual_controls.config_flow import (
            SECTIONS,
            normalize,
            schema_for,
        )
        from custom_components.contextual_controls.const import DEFAULTS

        for keys in SECTIONS.values():
            validated = normalize(schema_for(keys, DEFAULTS)({}))
            self.assertEqual(validated, {key: DEFAULTS[key] for key in keys})
        flow = await self.hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        self.assertEqual(flow["step_id"], "user")
        flow = await self.hass.config_entries.flow.async_configure(
            flow["flow_id"], {"name": "Contextual Controls"}
        )
        self.assertEqual(flow["step_id"], "entities")
        result = await self.hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "included_entities": ["light.test_contextual"],
                "included_domains": ["light"],
                "excluded_entities": ["light.excluded_contextual"],
            },
        )
        self.assertEqual(result["type"], "create_entry")
        entry = result["result"]
        await self.hass.async_block_till_done()
        self.assertEqual(entry.state, config_entries.ConfigEntryState.LOADED)
        coordinator = entry.runtime_data
        sensor = self.hass.states.get("sensor.contextual_controls")
        self.assertIsNotNone(sensor)
        self.assertEqual(sensor.state, "0")
        for _ in range(4):
            await self.hass.services.async_call(
                "light",
                "turn_on",
                {"entity_id": ["light.test_contextual", "light.excluded_contextual"]},
                blocking=True,
                context=Context(user_id="test_user"),
            )
        await self.hass.async_block_till_done()
        self.assertEqual(len(coordinator.history.records), 4)
        await coordinator.async_refresh()
        sensor = self.hass.states.get("sensor.contextual_controls")
        self.assertEqual(sensor.state, "1")
        self.assertEqual(sensor.attributes["entities"][0]["entity_id"], "light.test_contextual")
        self.assertEqual(
            sensor.attributes["entities"][0]["reason"],
            "Usato frequentemente in questa fascia oraria",
        )
        self.assertFalse(sensor.attributes["ai_used"])
        # State changes alone are not training events.
        self.hass.states.async_set(
            "light.test_contextual", "on", context=Context(user_id="test_user")
        )
        await self.hass.async_block_till_done()
        self.assertEqual(len(coordinator.history.records), 4)
        # Unload flushes; a fresh coordinator restores the real Store file.
        self.assertTrue(await self.hass.config_entries.async_unload(entry.entry_id))
        self.assertTrue(await self.hass.config_entries.async_setup(entry.entry_id))
        self.assertEqual(len(entry.runtime_data.history.records), 4)
        # Native options flow, automatic reload, pins and exclusion enforcement.
        flow = await self.hass.config_entries.options.async_init(entry.entry_id)
        self.assertEqual(flow["type"], "menu")
        flow = await self.hass.config_entries.options.async_configure(
            flow["flow_id"], {"next_step_id": "dashboard"}
        )
        result = await self.hass.config_entries.options.async_configure(
            flow["flow_id"],
            {
                "pinned_entities": ["scene.pin_contextual", "light.excluded_contextual"],
                "pinned_position": "before",
                "pinned_use_slots": True,
            },
        )
        self.assertEqual(result["type"], "create_entry")
        await self.hass.async_block_till_done()
        coordinator = entry.runtime_data
        self.assertEqual(len(coordinator.history.records), 4)
        entities = self.hass.states.get("sensor.contextual_controls").attributes["entities"]
        self.assertEqual(entities[0]["entity_id"], "scene.pin_contextual")
        self.assertNotIn("light.excluded_contextual", [row["entity_id"] for row in entities])
        self.assertEqual(len(self.calls), 4)  # No autonomous service calls.
        from homeassistant.exceptions import ServiceValidationError

        with self.assertRaises(ServiceValidationError):
            await self.hass.services.async_call(
                DOMAIN,
                "reset_learning",
                {"config_entry_id": entry.entry_id, "confirm": False},
                blocking=True,
            )
        self.assertEqual(len(coordinator.history.records), 4)
        await self.hass.services.async_call(
            DOMAIN,
            "reset_learning",
            {
                "config_entry_id": entry.entry_id,
                "confirm": True,
                "entity_id": "light.test_contextual",
            },
            blocking=True,
        )
        self.assertEqual(len(coordinator.history.records), 0)
        self.assertEqual(self.hass.states.get("sensor.contextual_controls").state, "1")
        from custom_components.contextual_controls.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        diagnostics = await async_get_config_entry_diagnostics(self.hass, entry)
        self.assertNotIn("test_user", str(diagnostics))
        self.assertNotIn("test_contextual", str(diagnostics))
        self.assertTrue(await self.hass.config_entries.async_unload(entry.entry_id))


if __name__ == "__main__":
    unittest.main()
