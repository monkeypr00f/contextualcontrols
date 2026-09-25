# Contextual Controls — Phase 1–2 and UI preview architecture

Decision record, updated 2026-09-25. Phase 2 adds local presence, context,
weekday, area and origin signals. Version 0.3.0 adds an early Lovelace card so
the ranked result can be evaluated before the complete Phase 4. AI remains
outside this release.

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
coordinator -> sensor attributes -> future frontend.

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
entities are excluded. Lock is opt-in by explicit entity selection; alarm and
siren are unsupported in Phase 1. No entity is ever executed by this integration.
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

## UI preview, distribution and future phases

Initial setup: instance name then monitored entities (recommended domains are
preselected). Only Statistical mode exists in this release; inert AI choices
would misrepresent implemented functionality. Options: General, Entities,
Learning, Context, Dashboard, Advanced and Reset. The Context section uses
native entity selectors and validates require-home configuration. AI arrives
with its implementation. Credentials, when added, belong to ConfigEntry.data.

Version 0.3.0 bundles a dependency-free preview card inside the integration.
The integration registers its immutable static route through
`async_register_static_paths` and its module through `add_extra_js_url`, both
present in the supported Core 2026.9.3 frontend/HTTP API. This makes the card
discoverable in the visual picker without editing dashboard resources or YAML.
The module URL includes the integration version to avoid stale browser caches.

The card reads only the ranked sensor and the states of the returned entities.
It renders at most 12 tiles and does not inspect the complete state registry.
An action occurs only after a user tap. Automatic tap toggles simple domains,
activates scene/script/button with their domain service, and opens more-info for
climate, cover, media player, lock and other controls without a safe one-tap
meaning. Hold always opens more-info. Text from entity states is assigned with
`textContent`, not injected as HTML.

HACS still recommends a separate Dashboard repository for the definitive Phase
4 distribution because Integration and Dashboard are different categories. The
bundled card is deliberately an evaluation slice. Once its interaction and
layout are accepted, the same custom element can move to a plugin repository;
the sensor contract and saved dashboard card configuration stay unchanged.

The current LLM API exposes tools **to** models; it is not a generic safe
completion/reranking API. Conversation can execute intents, and prompt wording
alone cannot prohibit actions. Therefore Phase 3 will introduce a provider
interface with disabled/local Ollama implementations and strict shortlist-only
JSON validation. Generic conversation-agent reranking remains disabled unless
a public API can guarantee no tool execution. Cache, privacy allowlists and
fallback are Phase 3 acceptance tests, not fabricated Phase 1 tests.

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
