# Optional physical terminal API

Contextual Controls runs without any physical terminal. No ESPHome firmware,
ESP32 dependency or hardware installation is included in this repository.

Optional clients, including Context Dial, consume a five-slot projection of
the existing ranking. Home Assistant owns filtering, limits, execution and
learning; clients submit slot references instead of executable entity IDs.
The separate [context-dial](https://github.com/monkeypr00f/context-dial)
repository owns firmware, wiring, UI and flashing.

## Configure terminals

Open **Settings → Devices & services → Contextual Controls → Configure →
Physical terminals**. Enter a terminal ID and select its areas using the
multi-area selector. Save and repeat for additional terminals. The internal
mapping format remains compatible with existing installations:

```text
cc_salotto:salotto+sala_da_pranzo+cucina,cc_camera:camera
```

`area_id` is the Home Assistant internal area ID (normally the lower-case name
shown in the URL or Developer Tools), not the display name. Save and reload the
integration. Each configured terminal publishes these client-readable states:

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

A physical client calls `contextual_controls.terminal_input` with:

| Input | Meaning |
|---|---|
| `select` | Move selection, or adjust the active LIGHT/NUMBER/CLIMATE/MEDIA control. |
| `adjust` | Enter brightness adjustment for a LIGHT control. |
| `activate` | Execute ACTION/TOGGLE; toggle LIGHT from the menu; enter NUMBER/CLIMATE/MEDIA adjustment or confirm an active value control. |
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
