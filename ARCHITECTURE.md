# Contextual Controls — Phase 1–4 architecture

Decision record, updated 2026-09-25. Phase 2 adds local presence, context,
weekday, area and origin signals. Version 0.3.0 adds an early Lovelace card so
the ranked result can be evaluated before the complete Phase 4. Phase 3 adds
optional shortlist-only AI reranking while retaining the statistical path.

## Verified baseline

The GitHub release API reports Home Assistant **2026.9.3** (2026-09-18) as
the current stable release. Its Python requirement is **>=3.14.2**. This is
the initial supported baseline; older releases are not claimed compatible.
APIs were checked in developer documentation and the **2026.9.3 tag**, not
guessed from older integration examples.

Sources:

- [Release metadata](https://api.github.com/repos/home-assistant/core/releases/latest)
- [Core and Context](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/core.py)
- [Config flow](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [Options flow](https://developers.home-assistant.io/docs/core/integration/options_flow/)
- [Selectors](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/helpers/selector.py)
- [Target resolution](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/helpers/target.py)
- [Store](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/helpers/storage.py)
- [HACS integration](https://www.hacs.xyz/docs/publish/integration/)
- [HACS metadata](https://www.hacs.xyz/docs/publish/start/)
- [HACS frontend plugin](https://www.hacs.xyz/docs/publish/plugin/)
- [Conversation](https://developers.home-assistant.io/docs/intent_conversation_api/)
- [LLM API](https://developers.home-assistant.io/docs/core/llm/)

## Boundaries and data flow

`call_service` -> origin classifier -> eligible-target intersection -> usage
records -> local Store -> deterministic scorer -> ranked/pinned selection ->
coordinator -> sensor attributes -> separate HACS Dashboard card.

- `models.py`: immutable usage/candidate/result records, no HA dependency.
- `history.py`: pure retention, validation and version migration functions.
- `storage.py`: HA Store adapter, delayed writes and flush on unload.
- `tracking.py`: bounded context ancestry, conservative origin classification
  and supported action map.
- `context.py`: pure presence and opaque context-snapshot comparison helpers.
- `eligibility.py`: inclusion/exclusion policy and ranking composition.
- `scoring.py`: circular local-time similarity, frequency, recency, origin
  confidence and simple current-state plausibility; no Home Assistant imports.
- `coordinator.py`: cached eligible IDs, event subscriptions, debounce,
  periodic evaluation and service-event ingestion.
- `config_flow.py`: two initial screens; sectioned OptionsFlowWithReload.
- `sensor.py`: result only; never calls a device service.

No Recorder dependency, SQL, monkeypatching, private HA attributes, network
requests, or autonomous device control. State changes maintain eligibility and
refresh current-state plausibility and configured signals; they are not training
events.

## Learning semantics and attribution

`EVENT_CALL_SERVICE` contains domain, service, service_data and Context. HA
fires it after schema validation but **before** service execution: records
represent command attempts, including possible failures, not verified effects.
It also records scene/script/button usage even when no state transition occurs.

An authenticated root context is a manual command with confidence 0.95. This
does not prove dashboard UI: REST clients using a user token can have the same
context. Parent contexts are not inferred to be manual even if `user_id` is
inherited. The coordinator keeps a five-minute, 4,096-entry in-memory ancestry
index populated by `automation_triggered`, `script_started`, and the
`conversation.process` service event. Proven Assist, script and automation
descendants receive confidence 0.85, 0.65 and 0.55. Everything else remains
unknown (0.2–0.25). Manual and Assist are enabled by default; automation, script
internals and unknown are opt-in. A directly pressed script is learned as the
script control before its internal actions are classified as script ancestry.

These component event names exist in Core 2026.9.3 but are not a generic public
ancestry API. Failure to observe one degrades to unknown classification; it
never upgrades an uncertain action to manual. The fallback uses only public
Event and Context fields.

The optional specific-user filter rejects unattributed records rather than
silently mixing another profile. Stored nullable user IDs prepare for future
profiles. Only context identifiers needed for short-lived deduplication are
kept in memory; full service payloads and command parameter values are not stored.
Deduplication is by context/entity/action, bounded in time and count.

Use public `helpers.target.TargetSelection` and
`async_extract_referenced_entity_ids`, including area/device/label resolution.
Deprecated service helpers are avoided. Only a known domain-specific set of
control services is learned; scene creation, reload, queries, etc. are ignored.
Target expansion is intersected with cached eligible entities and service
domain. Direct `script.<name>` calls are normalized to the script entity.

## Eligibility and safety

Explicit exclusions (entity/domain/area) always win, including over pinned IDs.
Inclusion is explicit IDs OR enabled domains, filtered by selected areas;
pinned IDs are explicit inclusion but obey the same area/exclusion policy.
Entity area overrides device area. Unsupported domains and disabled registry
entities are excluded. Lock, alarm and siren are opt-in by explicit entity
selection. Device actions occur only through a card tap or the public
`execute_slot` action and are never autonomous.
Unavailable/unknown ordinary controls are hidden, including pins; scenes and
buttons may have an `unknown` timestamp state before first use and remain valid.

The eligible index is built at setup and rebuilt on registry/topology changes,
not on every scoring pass. State creation/removal invalidates the index.
Normal state changes use constant-time membership checks. Ranking uses only
eligible states and a bounded 90-day/50,000-record history. Scoring runs in the
executor against immutable snapshots. Writes serialize immutable snapshots off
the event loop. A cap eviction is reported in diagnostics/debug metadata.

## Statistical model

Local clock distance wraps midnight (23:30 and 00:30 are 60 minutes apart).
Triangular similarity within the configured window has a 0.05 background
weight outside it. Records outside the learning period never contribute.
Recency slider 0 means no decay; 100 means rapid decay. Decay uses
`exp(-age_days / tau)`, with `tau = 90 - 87 * slider / 100` days.
Weighted evidence combines time, recency, origin confidence and a small
current-state penalty when a simple on/off command already matches state.
Phase 2 multiplies four bounded factors: exact weekday or workday/weekend,
historical/current presence agreement, active presence area, and equality of
configured context states. Mismatches reduce evidence but do not erase it.
Context values remain opaque strings; the integration does not infer device
semantics or normalize private state values.
Score is `1 - exp(-evidence / 3)`, in [0,1], with stable entity-ID tie breaks.

Cold start applies per entity before three records: recent controls (default),
frequent controls, domain defaults (explicit opt-in), or pinned only. The
confidence threshold still applies. Pins bypass statistical confidence and
can occupy slots or be additional; duplicates are removed. No artificial fill.
Reasons come from translation resources and identify the strongest matching
signal. If presence mode is `require_home`, no dynamic or pinned controls are
exposed until at least one configured person/device tracker is `home`, or a
configured binary sensor is `on`. Missing or unavailable presence fails closed.

## Persistence and lifecycle

Store is private and entry-specific. Version 1 records are migrated through
version 2 to version 3, which adds presence and configured context snapshots.
Old `user` records become `manual`; ambiguous old `child` records become
`unknown`. Unknown future
versions fail setup for retry instead of overwriting data. Invalid individual
records are rejected and counted. Retention is 90 days so increasing the UI
learning period can reuse already collected data. No pre-install history import.
The Store key survives restarts and reloads; removing the config entry removes
its history. Reset can filter by entity, user, both, or clear the entire entry.

Reset action requires `confirm: true`, and Options includes a dedicated
confirmation checkbox. HA service forms cannot force a modal confirmation;
the explicit boolean is enforced server-side. Ignoring learning is an options
list, separate from hiding controls; it also suppresses old evidence without
deleting other history. A later removal from this list can reuse retained data.

## Frontend distribution

The card is a separate HACS Dashboard repository:
`https://github.com/monkeypr00f/contextual-controls-card`. This follows the HACS
plugin contract (`dist/contextual-controls-card.js`) and lets frontend updates
arrive without a Home Assistant restart. Integration 0.5.0 no longer registers
HTTP static paths or extra JavaScript modules.

The public contract remains `type: custom:contextual-controls-card` plus the
ranked `entities` sensor attribute, so saved dashboard configuration survives
the split. Tiles, Compact and Chips are implemented without importing private
Home Assistant frontend modules. The visual editor uses the public
`getConfigForm` API. All service calls originate from a tap; complex and
sensitive domains use the public `hass-more-info` event.

## Phase 3 AI boundary

The current Home Assistant LLM API exposes tools **to** models; it is not a
generic completion/reranking API. The public Conversation API may execute
intents and its agent interface does not offer a provider-independent guarantee
that tools are disabled. Prompt wording alone cannot provide that guarantee.
For this reason the Home Assistant conversation-agent choice is documented as
unsupported in Phase 3 rather than presented as a working but unsafe option.

Phase 3 uses a small provider protocol with three implementations: disabled,
Ollama `/api/chat`, and an OpenAI-compatible `/v1/chat/completions` endpoint.
HTTP uses Home Assistant's shared async client session and `asyncio.timeout`;
there is no blocking I/O and no provider SDK dependency. The API key is kept in
`ConfigEntry.data`, never in options, diagnostics, prompts or logs.

The deterministic scorer remains authoritative for eligibility, safety,
confidence threshold and candidate generation. At most the configured top
6–30 statistical candidates are serialized. The provider returns only an
ordered JSON array of entity IDs. Parsing rejects malformed structures,
deduplicates IDs, drops IDs outside the shortlist and appends omitted valid
candidates in statistical order. AI output can therefore change order only;
it cannot introduce an entity, bypass exclusions, fill empty slots or call a
Home Assistant service.

Hybrid mode blends statistical and AI rank positions. AI-assisted mode gives
the model rank more weight, while retaining the same local candidate and output
boundaries. Disabled or failed AI always returns the original statistical
ranking. The sensor stays available and reports `ai_used`, `ai_provider`,
`ai_error` and the last successful AI update.

Privacy is an explicit allowlist for entity IDs, friendly names, current state,
area, aggregate usage statistics, exact current time, presence and configured
context entities. Raw history and user IDs are never serialized. Cache keys are
derived from the authorized prompt payload. Identical context reuses the last
result; changed context is rate-limited by the configured 5–120 minute minimum
AI interval and uses the statistical fallback while throttled.

## Apple Quick Access

Verified against the current public Home Assistant Companion documentation on
2026-09-26. A HACS integration cannot install an iOS/watchOS widget, App Intent,
Shortcut, complication, or Apple Watch item. Contextual Controls therefore
provides a server-side bridge to surfaces already implemented by the Companion
App:

- Apple App Intents `Perform action` can call any Home Assistant action and can
  receive action response data. It is the primary direct bridge for Shortcuts,
  Siri, Action Button, Control Center and the Shortcuts Apple Watch app.
- The Companion Apple Watch Home screen accepts user-selected Scripts, Scenes
  and iOS Actions. Static script wrappers can call a dynamic slot, but their
  Watch label and icon remain static. A custom integration has no public API to
  insert or rename these Watch items dynamically.
- The iOS Scripts and Open Page widgets support an accessory circular Lock
  Screen presentation. Details and Gauge can display templated data. The Custom
  Widget Beta supports System sizes only, not accessory Lock Screen sizes, and
  its refresh is controlled by iOS rather than being real time.
- Live Activities are state displays updated by notifications. Their documented
  tap opens the Companion App or a configured URL; they do not expose the
  required dynamic action-button grid and are not used as the control surface.
- Watch complications can render sensor templates, but updates are budgeted and
  they are a display/launch surface rather than a dynamic six-button API.

Sources: [Apple App Intents](https://companion.home-assistant.io/docs/integrations/siri-shortcuts/),
[Apple Watch](https://companion.home-assistant.io/docs/apple-watch/),
[complications](https://companion.home-assistant.io/docs/apple-watch/complications/),
[iOS widgets](https://companion.home-assistant.io/docs/integrations/ios-widgets/),
and [Live Activities](https://companion.home-assistant.io/docs/notifications/live-activities/).

The coordinator's already selected `entities` rows remain the only ranking
source. `SlotManager` snapshots those rows in memory; it never scores, reads
history, or calls an AI provider. Each configured slot is exposed as a stable
sensor and carries target ID, name, icon, state, score, reason, recommended
action, generation and update time. Slot entities read only coordinator memory.

Ranking changes pass through a configurable 0/30/60/120/300-second stability
window. A still-valid published target remains in its slot during that window;
unavailable, removed or newly forbidden targets are replaced immediately.
Every target-map change increments a generation. Clients that first call
`get_slot` can pass its `entity_id` as `expected_entity_id` to `execute_slot`;
any mismatch fails with `stale_slot` before a device action is called. Execution
is serialized per config entry and uses the captured snapshot, so concurrent
refreshes cannot redirect an in-flight tap.

`get_slot` is response-only. `execute_slot` supports optional response data and
uses public `hass.services.async_call` with the caller Context. Automatic action
resolution is centralized and conservative: toggles for lights/switches/fans
and input booleans; activation for scenes/scripts; press for buttons; open or
close only for unambiguous cover states; media play/pause only when advertised;
climate, locks, alarms, sirens, vacuums and ambiguous states require the app or
an explicitly designed future action. Safe/Balanced/Direct policy and an
explicit sensitive-entity list are enforced after resolution and before the
service call. Confirmation never invents an otherwise unsupported command.

Successful quick-access execution records one `quick_access` Usage entry with
the optional, allowlisted source detail and configured confidence weight. Its
nested Home Assistant service event is suppressed from normal ingestion to
avoid double learning. The tap path uses cached coordinator data only: no AI,
history query or ranking refresh is performed. Slot snapshots are intentionally
ephemeral across integration reloads; retained learning is persistent, while a
new process safely publishes a fresh generation before accepting a tap.

## Adaptive Learning

Adaptive Learning is an optional local layer after the existing deterministic
scorer. It never changes eligibility, minimum-confidence filtering, pinned
composition or Quick Access safety. Disabling it returns the exact base ranking.

The event model reuses accepted `Usage` records. `LearningEngine.record_action`
receives the same significant action only after origin classification, target
validation and deduplication. A bounded, non-persistent recent-action buffer is
kept per user plus a global buffer. Source weights and the original confidence
scale evidence without promoting raw `state_changed` events.

The transition model stores compact A→B and bounded A→B→C aggregates rather
than rescanning raw history. Three-step chains use only the last two significant
actions for the same actor; arbitrary-length chains are intentionally excluded.
Each aggregate records raw and weighted counts, last observation, delay sum, a bounded delay sample for the median, and distributions for
morning/afternoon/evening/night, weekday/weekend and home/away/unknown. Sequence
scores require the configured minimum raw support, decay by age, compare the
current delay with the learned delay, and softly match the current context.
Old or low-support patterns therefore cannot dominate the base score.

The exposure model stores one compact row per published suggestion generation:
timestamp, entity, final/base/adaptive rank, score, source confidence, context
hash, slot, generation, accepted state and delay. Identical rankings are
debounced, and an ordinary coordinator refresh is recorded as an `unknown`
exposure with reduced confidence because the integration cannot prove the
dashboard was visible. Quick Access execution records a high-confidence
exposure only when the tap proves interaction; merely publishing a Watch slot
does not count as a view.

An action within the acceptance window resolves matching exposure rows as
accepted. Expired unresolved rows become ignored. Incremental feedback
aggregates are segmented only by time bucket, weekday/weekend and presence,
with an all-context fallback. Smoothed acceptance uses Beta(2, 2). Penalties do
not start before the configured exposure threshold, remain bounded by the
configured strength and recover as later acceptances change the aggregate.
Frequently accepted suggestions receive a separately bounded boost.

For each candidate the predictive layer computes sequence, acceptance and
ignore signals in [0, 1]. It first builds an adaptive target from the base score:

`target = base + sequence_influence * sequence * (1-base)
               + acceptance_boost * acceptance * (1-base)
               - ignored_penalty * ignore * base`

and then interpolates `final = lerp(base, clamp(target), prediction_influence)`.
All percentages are divided by 100. The resulting score remains in [0, 1].
Debug output retains base and every adaptive term. Standard reasons remain
positive or neutral; full negative evidence is debug-only.

Storage remains one private Home Assistant `Store` per ConfigEntry. Schema 6
contains the existing `records` array plus an `adaptive` object with transition
and three-step chain aggregates, live/recent exposures, feedback aggregates and
metrics. The Store migration adds an empty `chains` collection without changing
old records or existing adaptive evidence.
Writes remain delayed and snapshot-based. Raw exposures follow configurable
30–365-day retention and strict capacity limits; compact aggregates decay and
are removed when stale. The recent-action buffer intentionally starts empty
after restart, while learned transitions, feedback and metrics persist.

Learning scope can be global, per-user or hybrid. Global aggregates never store
a user identifier. Per-user aggregates use the Context user ID internally.
Hybrid prefers a sufficiently supported user aggregate and otherwise falls
back to global evidence. Diagnostics expose counts and rates, not identities or
raw histories. Reset can independently clear historical, sequence or feedback
data, or filter adaptive and historical data by user/entity.

Top-1 and Top-3 hit rates use the first significant action observed during an
exposure window. The same observation updates offline `base_top3_hit` and
`adaptive_top3_hit` counters using ranks captured before AI; users still see one
normal ranking and are never randomized. AI, when enabled, receives only the
already calculated sequence score, smoothed acceptance rate and ignore penalty
under the existing usage-statistics privacy switch. The model cannot edit those
values or add candidates.

Cold start is conservative: sequence evidence below minimum support is zero,
feedback below minimum exposures has no penalty, and the existing scorer is the
only signal. Season, temperature, sunlight and sunrise/sunset can later extend
the compact context segment without changing the storage contract.

## Verification policy

Pure pytest tests exercise real scoring and policy. Following the user's
request to use their existing HA installation, no second HA runtime was
installed locally. `tests/runtime_check.py` uses `IsolatedAsyncioTestCase`, also
runnable by pytest, and the real 2026.9.3 libraries already in their container.
It exercises config flow, Phase 1 ConfigEntry and Store migrations, options
reload, origin tracking, presence gating, context snapshots, sensor state,
Store persistence (including reading from a fresh Python process), and reset.
Its temporary configuration and dummy services do not connect to the live HA
process. No mock replacement of the HA APIs is used.

CI runs ruff, mypy on the pure core, pytest, syntax compilation, a matching HA
container lifecycle test, hassfest and HACS. The actual instance was separately
used to verify UI onboarding, translated selectors, options, pinned output and
reload. See `docs/VERIFICATION.md` for results and remaining publication work.
