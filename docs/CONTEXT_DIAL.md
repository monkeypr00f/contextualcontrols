# Context Dial (ESPHome)

Context Dial is a physical five-action terminal for Contextual Controls. It
does not contain entity IDs, ranking weights, or device-control rules. The
integration projects its current ranked result into per-terminal sensor states
and resolves each selected slot again in Home Assistant.

## Configure terminals

Open **Settings → Devices & services → Contextual Controls → Configure →
Physical terminals** and set `Terminal-to-area mappings` to comma-separated
`terminal_id:area_id` pairs:

```text
cc_salotto:salotto+sala_da_pranzo+cucina,cc_camera:camera
```

`area_id` is the Home Assistant internal area ID (normally the lower-case name
shown in the URL or Developer Tools), not the display name. Save and reload the
integration. Each configured terminal publishes these ESPHome-readable states:

```text
sensor.contextual_controls_<terminal>_title
sensor.contextual_controls_<terminal>_status
sensor.contextual_controls_<terminal>_mode
sensor.contextual_controls_<terminal>_revision
sensor.contextual_controls_<terminal>_feedback
sensor.contextual_controls_<terminal>_action_1 … _action_5
```

The `+` operator assigns multiple areas to one terminal; commas separate terminals.
The `revision` protects against a command from an old on-screen list. Rows are
selected from the complete ranking before applying the terminal's area filter
and five-slot limit. Available permitted entities without learned scores fill
remaining slots as manual controls (`source: available`, `score: 0`). Exclusions
remain authoritative. Slots are held stable with the existing Quick Access
stability interval and frozen during adjustment to keep the edited target stable.

## Wire protocol

The ESPHome terminal calls `contextual_controls.terminal_input` with:

| Input | Meaning |
|---|---|
| `select` | Move selection, or adjust the currently active NUMBER/CLIMATE/MEDIA control. |
| `activate` | Execute ACTION/TOGGLE; enter or confirm adjustment mode for NUMBER/CLIMATE/MEDIA. |
| `back` | Leave adjustment mode; it is home/no-op from the main list. |

The service only accepts a terminal id, 1-based slot, delta and revision. It
never accepts an executable entity id from the ESP. `terminal_input` returns a
response for diagnostics; `contextual_controls_terminal_input` is emitted for
automations and observability and includes timestamp, terminal, area, slot,
displayed candidate IDs and outcome.

Successful ACTION/TOGGLE execution reuses the existing safety policy and records
the use as `quick_access` with source detail `context_dial`. It also records a
forced exposure at the selected terminal position, so the existing acceptance,
sequence and ranking logic can learn from it without a second model.

## Adjustment behavior

Adjustment is intentionally constrained:

- `number`: uses the entity `step`, `min` and `max`, calling `number.set_value`.
- `climate`: uses `target_temp_step`, `min_temp` and `max_temp`, calling
  `climate.set_temperature`.
- `media_player`: adjusts `volume_level` in 5% increments via
  `media_player.volume_set`.
- dimmable `light`: adjusts brightness in 5% increments via `light.turn_on`.
- positioned `cover`: adjusts position in 5% increments via
  `cover.set_cover_position`.

KO or pressing the encoder returns to the menu. Each rotation applies immediately;
KO does not undo already-applied values. A dimmable light is adjustable even
when off and its brightness attribute is temporarily missing. Zero turns it off.
The next ranking/state update refreshes the displayed value.

Every action entity has a compact label as its state and additionally publishes
`kind`, `value`, `min`, `max`, `step`, `unit`, current state, score and rank
reason as attributes. `feedback` is a small transport state (`ready`, `adjust`,
`ok` or an error reason) for physical clients that need to show a result.

## ESPHome

Use [`context_dial.yaml`](../../deliverables/context_dial/esphome/context_dial.yaml).
It is an LVGL UI with a focused three-card carousel, value-control, loading,
result, offline and Display settings views. Its only per-device substitutions are
`device_name`, `friendly_name`, `terminal_id` and `cc_entity_prefix`.

It expects the validated wiring: TRA/4, TRB/5, PSH/6, KO/7, RES/8, DC/9,
CS/10, SDA/11, SCL/12 and BLK/3. It uses a 100% → 15% after 30 seconds → off
after 120 seconds policy; the first next knob/button input only wakes the
display. Click the selected light to adjust its HA brightness; double-click KO
for the separate **Display ESPHome** backlight view. The firmware
uses ESPHome's native multi-click recognizer and preserves the Display view
when Home Assistant sends control-mode or result updates.
Enable
**Allow the device to perform Home Assistant actions** in the ESPHome device's
Configure dialog before testing.
