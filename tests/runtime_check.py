"""Real-core smoke test. Runs inside an existing HA container, in a temp config.

Does not connect to the running HA process or command real devices.
Run: python -m unittest tests.runtime_check -v
"""

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from homeassistant import config_entries, loader
from homeassistant.components.automation import EVENT_AUTOMATION_TRIGGERED
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry, device_registry, entity_registry
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

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
        self.hass.states.async_set("person.contextual_user", "not_home")
        self.hass.states.async_set("input_boolean.contextual_night", "on")
        self.calls = []

        async def dummy(call):
            self.calls.append(call)

        self.hass.services.async_register("light", "turn_on", dummy)
        self.hass.services.async_register("light", "turn_off", dummy)

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)
        await self.hass.async_block_till_done()
        self.tmp.cleanup()

    async def test_store_migration_and_future_version(self):
        from homeassistant.exceptions import UnsupportedStorageVersionError

        from custom_components.contextual_controls.history import encode
        from custom_components.contextual_controls.models import Usage
        from custom_components.contextual_controls.storage import History

        data = encode([Usage(dt_util.utcnow(), "light.test", None, "unknown", "turn_on", 0.2)])
        del data["records"][0]["confidence"]
        del data["records"][0]["area_id"]
        history = History(self.hass, "migration")
        path = Path(history.store.path)

        def write(version):
            path.parent.mkdir(exist_ok=True)
            path.write_text(
                json.dumps(
                    {"version": version, "minor_version": 1, "key": history.store.key, "data": data}
                )
            )

        await asyncio.to_thread(write, 1)
        await history.async_load(dt_util.utcnow())
        self.assertEqual(len(history.records), 1)
        self.assertEqual(history.records[0].confidence, 0.2)
        self.assertEqual(json.loads(await asyncio.to_thread(path.read_text))["version"], 4)
        future = History(self.hass, "future")
        path = Path(future.store.path)
        await asyncio.to_thread(write, 999)
        with self.assertRaises(UnsupportedStorageVersionError):
            await future.async_load(dt_util.utcnow())
        self.assertEqual(json.loads(await asyncio.to_thread(path.read_text))["version"], 999)

    async def test_area_targets_and_nonmanual_calls(self):
        registry = entity_registry.async_get(self.hass)
        area = area_registry.async_get(self.hass).async_create("Contextual test area")
        registered = registry.async_get_or_create("light", "test", "contextual_area")
        registry.async_update_entity(registered.entity_id, area_id=area.id)
        self.hass.states.async_set(registered.entity_id, "off")
        flow = await self.hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        flow = await self.hass.config_entries.flow.async_configure(
            flow["flow_id"], {"name": "Area test"}
        )
        result = await self.hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {"included_domains": ["light"], "included_entities": [], "excluded_entities": []},
        )
        entry = result["result"]
        await self.hass.async_block_till_done()
        self.assertEqual(entry.state, config_entries.ConfigEntryState.LOADED)
        automation_context = Context()
        self.hass.bus.async_fire(
            EVENT_AUTOMATION_TRIGGERED,
            {"entity_id": "automation.test", "name": "test"},
            context=automation_context,
        )
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {"area_id": area.id},
            context=automation_context,
            blocking=True,
        )
        for context in (Context(user_id="test_user", parent_id="parent"), Context()):
            await self.hass.services.async_call(
                "light", "turn_on", {"area_id": area.id}, context=context, blocking=True
            )
        await self.hass.async_block_till_done()
        self.assertEqual(len(entry.runtime_data.history.records), 0)
        assist_context = Context(user_id="test_user")
        self.hass.bus.async_fire(
            EVENT_CALL_SERVICE,
            {"domain": "conversation", "service": "process", "service_data": {}},
            context=assist_context,
        )
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {"area_id": area.id},
            context=Context(user_id="test_user", parent_id=assist_context.id),
            blocking=True,
        )
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {"area_id": area.id},
            context=Context(user_id="test_user"),
            blocking=True,
        )
        await self.hass.async_block_till_done()
        records = list(entry.runtime_data.history.records)
        self.assertEqual(len(records), 2)
        self.assertEqual([record.source for record in records], ["assist", "manual"])
        self.assertTrue(all(record.entity_id == registered.entity_id for record in records))
        self.assertTrue(all(record.area_id == area.id for record in records))
        self.assertTrue(await self.hass.config_entries.async_unload(entry.entry_id))

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
            "Abitudine di questo tipo di giornata",
        )
        self.assertFalse(sensor.attributes["ai_used"])
        # Provider failures preserve the statistical result and sensor availability.
        from custom_components.contextual_controls.ai import AIManager, AIProviderError

        class FailingProvider:
            async def async_order(self, prompt, allowed):
                raise AIProviderError("timeout")

        coordinator.options["mode"] = "hybrid"
        coordinator.options["ai_provider"] = "ollama"
        coordinator._ai_manager = AIManager(FailingProvider(), 15)
        coordinator._ai_status = "ready"
        await coordinator.async_refresh()
        sensor = self.hass.states.get("sensor.contextual_controls")
        self.assertEqual(sensor.state, "1")
        self.assertFalse(sensor.attributes["ai_used"])
        self.assertEqual(sensor.attributes["ai_error"], "timeout")
        self.assertEqual(sensor.attributes["entities"][0]["entity_id"], "light.test_contextual")
        coordinator._ai_manager = None
        coordinator.options["ai_provider"] = "disabled"
        # Context options reload the entry. Require-home gates the full output,
        # then presence/context are captured on the next voluntary command.
        flow = await self.hass.config_entries.options.async_init(entry.entry_id)
        flow = await self.hass.config_entries.options.async_configure(
            flow["flow_id"], {"next_step_id": "context"}
        )
        result = await self.hass.config_entries.options.async_configure(
            flow["flow_id"],
            {
                "presence_entities": ["person.contextual_user"],
                "presence_mode": "require_home",
                "context_entities": ["input_boolean.contextual_night"],
            },
        )
        self.assertEqual(result["type"], "create_entry")
        await self.hass.async_block_till_done()
        coordinator = entry.runtime_data
        await coordinator.async_refresh()
        self.assertEqual(self.hass.states.get("sensor.contextual_controls").state, "0")
        self.hass.states.async_set("person.contextual_user", "home")
        await self.hass.async_block_till_done()
        await coordinator.async_refresh()
        self.assertEqual(self.hass.states.get("sensor.contextual_controls").state, "1")
        await self.hass.services.async_call(
            "light",
            "turn_off",
            {"entity_id": "light.test_contextual"},
            blocking=True,
            context=Context(user_id="test_user"),
        )
        record = coordinator.history.records[-1]
        self.assertTrue(record.presence_home)
        self.assertEqual(record.context_states, (("input_boolean.contextual_night", "on"),))
        # State changes alone are not training events.
        self.hass.states.async_set(
            "light.test_contextual", "on", context=Context(user_id="test_user")
        )
        await self.hass.async_block_till_done()
        self.assertEqual(len(coordinator.history.records), 5)
        # Unload flushes; a fresh coordinator restores the real Store file.
        self.assertTrue(await self.hass.config_entries.async_unload(entry.entry_id))

        # A new process proves persistence without reusing HA's Store cache.
        reader = """
import asyncio, sys
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from custom_components.contextual_controls.storage import History
async def read():
    hass = HomeAssistant(sys.argv[1])
    history = History(hass, sys.argv[2])
    await history.async_load(dt_util.utcnow())
    print(len(history.records))
    await hass.async_stop(force=True)
asyncio.run(read())
"""
        completed = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", reader, self.tmp.name, entry.entry_id],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        self.assertEqual(completed.stdout.strip(), "5")
        self.assertTrue(await self.hass.config_entries.async_setup(entry.entry_id))
        self.assertEqual(len(entry.runtime_data.history.records), 5)
        # A Phase 1 ConfigEntry maps old source names and gains Phase 2 defaults.
        old_options = dict(entry.options)
        for key in (
            "consider_weekday",
            "weekday_mode",
            "presence_entities",
            "presence_mode",
            "context_entities",
        ):
            old_options.pop(key, None)
        old_options["learn_sources"] = ["user"]
        self.hass.config_entries.async_update_entry(entry, options=old_options, version=1)
        self.assertTrue(await self.hass.config_entries.async_reload(entry.entry_id))
        self.assertEqual(entry.version, 3)
        self.assertEqual(entry.options["learn_sources"], ["manual"])
        self.assertEqual(entry.options["presence_mode"], "signal")
        self.assertEqual(entry.options["ai_provider"], "disabled")
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
        self.assertEqual(len(coordinator.history.records), 5)
        entities = self.hass.states.get("sensor.contextual_controls").attributes["entities"]
        self.assertEqual(entities[0]["entity_id"], "scene.pin_contextual")
        self.assertNotIn("light.excluded_contextual", [row["entity_id"] for row in entities])
        self.assertEqual(len(self.calls), 5)  # No autonomous service calls.
        from homeassistant.exceptions import ServiceValidationError

        with self.assertRaises(ServiceValidationError):
            await self.hass.services.async_call(
                DOMAIN,
                "reset_learning",
                {"config_entry_id": entry.entry_id, "confirm": False},
                blocking=True,
            )
        self.assertEqual(len(coordinator.history.records), 5)
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
        # The AI options flow stores credentials in ConfigEntry.data, then reloads.
        flow = await self.hass.config_entries.options.async_init(entry.entry_id)
        flow = await self.hass.config_entries.options.async_configure(
            flow["flow_id"], {"next_step_id": "ai"}
        )
        flow = await self.hass.config_entries.options.async_configure(
            flow["flow_id"], {"ai_provider": "openai_compatible"}
        )
        self.assertEqual(flow["step_id"], "ai_openai_compatible")
        result = await self.hass.config_entries.options.async_configure(
            flow["flow_id"],
            {
                "openai_endpoint": "http://local-model",
                "openai_model": "test-model",
                "ai_timeout_seconds": 5,
                "ai_temperature": 0.1,
                "api_key": "diagnostic-secret",
            },
        )
        self.assertEqual(result["type"], "create_entry")
        await self.hass.async_block_till_done()
        self.assertEqual(entry.data["openai_api_key"], "diagnostic-secret")
        coordinator = entry.runtime_data
        self.assertEqual(coordinator.options["ai_provider"], "openai_compatible")
        from custom_components.contextual_controls.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        diagnostics = await async_get_config_entry_diagnostics(self.hass, entry)
        self.assertNotIn("test_user", str(diagnostics))
        self.assertNotIn("test_contextual", str(diagnostics))
        self.assertNotIn("diagnostic-secret", str(diagnostics))
        self.assertTrue(await self.hass.config_entries.async_unload(entry.entry_id))

    async def test_quick_access_services_safety_learning_and_concurrency(self):
        flow = await self.hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        flow = await self.hass.config_entries.flow.async_configure(
            flow["flow_id"], {"name": "Quick access"}
        )
        result = await self.hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "included_entities": ["light.test_contextual"],
                "included_domains": [],
                "excluded_entities": [],
            },
        )
        entry = result["result"]
        await self.hass.async_block_till_done()
        coordinator = entry.runtime_data
        coordinator.options["pinned_entities"] = ["light.test_contextual"]
        await coordinator.async_refresh()
        self.assertIsNotNone(self.hass.states.get("sensor.contextual_control_1"))

        response = await self.hass.services.async_call(
            DOMAIN,
            "get_slot",
            {"slot": 1},
            blocking=True,
            return_response=True,
        )
        self.assertEqual(response["entity_id"], "light.test_contextual")
        self.assertEqual(response["recommended_action"], "toggle")

        stale = await self.hass.services.async_call(
            DOMAIN,
            "execute_slot",
            {"slot": 1, "expected_entity_id": "light.somewhere_else"},
            blocking=True,
            return_response=True,
        )
        self.assertEqual(stale["reason"], "stale_slot")
        self.assertEqual(coordinator.stale_slot_rejections, 1)

        active = 0
        maximum_active = 0

        async def toggle(call):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            self.calls.append(call)

        self.hass.services.async_register("light", "toggle", toggle)
        before = len(coordinator.history.records)
        first, second = await asyncio.gather(
            coordinator.async_execute_slot(
                1,
                expected_entity_id="light.test_contextual",
                mode="automatic",
                confirmed=False,
                source="apple_watch",
                context=Context(user_id="test_user"),
            ),
            coordinator.async_execute_slot(
                1,
                expected_entity_id="light.test_contextual",
                mode="automatic",
                confirmed=False,
                source="ios_lock_screen",
                context=Context(user_id="test_user"),
            ),
        )
        self.assertTrue(first["success"] and second["success"])
        self.assertEqual(maximum_active, 1)
        self.assertEqual(len(coordinator.history.records), before + 2)
        self.assertEqual(coordinator.history.records[-2].source, "quick_access")
        self.assertEqual(coordinator.history.records[-2].source_detail, "apple_watch")
        self.assertEqual(coordinator.history.records[-1].source_detail, "ios_lock_screen")

        class ForbiddenAI:
            async def async_rerank(self, *args, **kwargs):
                raise AssertionError("slot execution must not call AI")

        coordinator._ai_manager = ForbiddenAI()
        direct = await coordinator.async_execute_slot(
            1,
            expected_entity_id="light.test_contextual",
            mode="automatic",
            confirmed=False,
            source="shortcut",
            context=Context(user_id="test_user"),
        )
        self.assertTrue(direct["success"])

        coordinator.options["quick_access_sensitive_entities"] = ["light.test_contextual"]
        blocked = await coordinator.async_execute_slot(
            1,
            expected_entity_id="light.test_contextual",
            mode="execute",
            confirmed=True,
            source="shortcut",
            context=Context(user_id="test_user"),
        )
        self.assertEqual(blocked["reason"], "requires_confirmation")
        self.assertEqual(coordinator.sensitive_action_rejections, 1)
        empty = await coordinator.async_execute_slot(
            6,
            expected_entity_id=None,
            mode="automatic",
            confirmed=False,
            source="unknown",
            context=Context(user_id="test_user"),
        )
        self.assertEqual(empty["reason"], "empty_slot")
        invalid = await coordinator.async_execute_slot(
            7,
            expected_entity_id=None,
            mode="automatic",
            confirmed=False,
            source="unknown",
            context=Context(user_id="test_user"),
        )
        self.assertEqual(invalid["reason"], "invalid_slot")
        self.hass.states.async_set("light.test_contextual", "unavailable")
        unavailable = coordinator.quick_access_slot(1)
        self.assertEqual(unavailable["reason"], "unavailable_target")
        self.assertTrue(await self.hass.config_entries.async_unload(entry.entry_id))


if __name__ == "__main__":
    unittest.main()
