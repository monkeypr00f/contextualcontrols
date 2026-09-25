# Contextual Controls — Phase 1 architecture

Decision record, 2026-09-24. Scope: Phase 1 only. No AI, presence modelling,
weekday modelling or custom Lovelace card is implemented in this phase.

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
- `tracking.py`: conservative context classification and supported action map.
- `eligibility.py`: inclusion/exclusion policy and ranking composition.
- `scoring.py`: circular local-time similarity, frequency, recency, origin
  confidence and simple current-state plausibility; no Home Assistant imports.
- `coordinator.py`: cached eligible IDs, event subscriptions, debounce,
  periodic evaluation and service-event ingestion.
- `config_flow.py`: two initial screens; sectioned OptionsFlowWithReload.
- `sensor.py`: result only; never calls a device service.

No Recorder dependency, SQL, monkeypatching, private HA attributes, network
requests, or autonomous device control. State changes maintain eligibility and
refresh current-state plausibility; they are **not** training events in Phase 1.

## Learning semantics and attribution

`EVENT_CALL_SERVICE` contains domain, service, service_data and Context. HA
fires it after schema validation but **before** service execution: records
represent command attempts, including possible failures, not verified effects.
It also records scene/script/button usage even when no state transition occurs.

Phase 1 accepts a direct context with `user_id` and without `parent_id` as an
authenticated user command, confidence 0.9. This does not prove dashboard UI:
REST clients using a user token can have the same context. Parent contexts are
not inferred to be manual even if user_id is inherited. Unattributed and child
commands can be opted into with lower confidence but are off by default.
Assist without an authenticated direct user context is not reliably detected;
automation versus script ancestry is deferred to Phase 2. UI labels describe
these limits instead of presenting inaccurate origin toggles.

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
Score is `1 - exp(-evidence / 3)`, in [0,1], with stable entity-ID tie breaks.

Cold start applies per entity before three records: recent controls (default),
frequent controls, domain defaults (explicit opt-in), or pinned only. The
confidence threshold still applies. Pins bypass statistical confidence and
can occupy slots or be additional; duplicates are removed. No artificial fill.
Reasons come from translation resources, with counts computed deterministically.
Context/presence/area-affinity/weekday factors will be added in Phase 2, not
simulated with invented data in Phase 1.

## Persistence and lifecycle

Store is private and entry-specific. Version 1 records are migrated to version
2 with a nullable area_id and conservative default confidence. Unknown future
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

## UI, distribution and future phases

Initial setup: instance name then monitored entities (recommended domains are
preselected). Only Statistical mode exists in this release; inert AI choices
would misrepresent implemented functionality. Options: General, Entities,
Learning, Dashboard, Advanced and Reset. Context and AI sections arrive with
their implementations. Credentials, when added, belong to ConfigEntry.data.

One integration directory is delivered by HACS. The Phase 4 card should be a
separate HACS dashboard repository: integration and frontend have different
distribution categories. It can share a source workspace later, but the
integration must not assume HACS installs root-level frontend files.
This repository can be tested locally before publication; a real public GitHub
URL, metadata and HACS validation are required before calling it published or
HACS-verified. Default-store inclusion and brands submission are separate work.

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
It exercises config flow, options reload, service tracking, sensor state,
Store persistence (including reading from a fresh Python process), and reset.
Its temporary configuration and dummy services do not connect to the live HA
process. No mock replacement of the HA APIs is used.

CI runs ruff, mypy on the pure core, pytest, syntax compilation, a matching HA
container lifecycle test, hassfest and HACS. The actual instance was separately
used to verify UI onboarding, translated selectors, options, pinned output and
reload. See `docs/VERIFICATION.md` for results and remaining publication work.
