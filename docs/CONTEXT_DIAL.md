# Context Dial — optional companion

Version 0.11.0 introduces the [configurable terminal / schema 2](CONFIGURABLE_TERMINAL.md):
ordered fixed entities, optional contextual suggestions, native KO controls,
live state and an independent persistent ESPHome display-brightness number.
Update the integration and the schema-2 firmware together.

The ESP32/LVGL firmware and hardware documentation have moved to the independent
[`context-dial`](https://github.com/monkeypr00f/context-dial) repository.
They are not required to install Contextual Controls.

This integration retains the optional [physical terminal API](TERMINAL_API.md).
Existing terminal IDs, area mappings, sensors and services are unchanged.

See the [companion README](https://github.com/monkeypr00f/context-dial#readme)
for firmware compatibility, hardware, configuration and flashing.
