# BGAnalyzer implementation specification

Revision: 1.0, 9 September 2026. Status: implementation-ready engineering plan with explicit onboarding unknowns and numerical-release gates. This document specifies work; it does not claim that an application, algorithm port, or clinical validation already exists.

## 1. Product contract

Build a native Linux desktop application for one adult user's retrospective type 1 diabetes analysis. Read Nightscout, maintain a local history, show glucose alongside recorded insulin and meals, identify repeat patterns, and present reviewable basal/IC/ISF candidates with reproducible supporting evidence. The user manually enters any chosen changes into AAPS; AAPS subsequently uploads its profile to Nightscout.

The application owns its local model runtime: installing or starting Ollama is never required. All patient-data analysis and AI inference run on this computer. Network traffic is limited to the configured Nightscout origin, explicitly requested model downloads, and explicitly requested application updates. No telemetry, cloud AI, remote embeddings, remote crash reporting, or automatic sharing.

Suggestions must say what changed, which observations support it, what contradicts it, which algorithm produced it, what was excluded, and what remains uncertain. Explanations are an evidence-based account of the calculation, not a model's hidden reasoning transcript. A chart and calculation ledger must remain available even if AI fails.

Never implement pump control, Nightscout writes, AAPS writeback, insulin bolus advice for the current glucose, or an emergency alarm replacement. Do not interpret the word "continuous" as continually changing the recommended profile: synchronize continuously while running, refresh descriptive analysis hourly, and generate retrospective profile candidates at most once per completed analysis day unless requested manually.

Deliver the full numerical-candidate feature, not only a chatbot or dashboard. However, numerical display remains disabled until the engineering and independent diabetes-domain validation gates in section 18 pass. A disclaimer or user checkbox cannot substitute for those gates. Working software and medically reliable recommendations are separate claims.

## 2. Confirmed context and observed integration

### User-confirmed

| Item | Requirement |
|---|---|
| Pump | Omnipod DASH |
| Insulin | NovoRapid, insulin aspart; do not infer AAPS curve settings from the brand |
| Loop | AndroidAPS with xDrip+ and Nightscout backup/viewing |
| Host | Bazzite stable, x86_64, KDE Plasma/Wayland |
| CPU/RAM | Ryzen 9 7900X; approximately 32 GB installed RAM |
| GPU | Radeon RX 7900 XTX; prefer Vulkan and explicitly select this discrete GPU |
| Screen | 3440 × 1440; also support 1280 × 800 and fractional scaling |
| Settings workflow | Suggestions only; user enters changes in AAPS |
| History | User estimates three months; verify, do not assume retention |

### Read-only discovery performed for this plan

Requests were made to the user-provided Nightscout origin on 9 September 2026. No secret was needed or used, and no raw patient records were saved to this repository. The URL is configured at onboarding; do not embed the personal origin in source code or fixtures.

* `/api/v1/status.json` returned HTTP 200 and Nightscout **15.0.8**.
* `/api/v3/version` returned HTTP 200; unauthenticated `/api/v3/status` returned **401**. Public v1 reads do not imply v3 authentication succeeds.
* v1 entries, treatments, profile, devicestatus, and food collection reads succeeded without credentials.
* The latest sampled uploaded configuration reports **AAPS 3.4.2.1**, **SMB**, and `configuration.apsConfiguration.use_dynamic_sensitivity=false`.
* Profile metadata reports `units=mmol`, `timezone=Europe/London`.
* The sampled configuration was dated **2026-09-08 17:30:00 UTC**; the newest sampled glucose was **2026-09-08 17:29:29 UTC**. These were historical at inspection time. Do not describe successful HTTP requests as proof of current glucose freshness.
* Treatment sample: Temp Basal, Meal Bolus, Bolus Wizard, Temporary Target, OpenAPS Offline, Site Change, Insulin Change, and Announcement. Meal Bolus records have an `isSMB` field. **An event named Meal Bolus is not necessarily a meal bolus.**
* Temp Basal fields include `absolute`, `rate`, `duration`, `durationInMilliseconds`, `pumpId`, `type`, and sometimes `endId`. Records include validity flags.
* Bolus Wizard has `bolusCalculatorResult`; it must not be counted as an additional delivered bolus without confirmed delivery semantics.
* The newest sampled devicestatus record had an **empty `openaps` object**. Therefore uploaded IOB, COB, activity, and effective sensitivity cannot be assumed available.
* `/food` returned an empty sample. Treatment carbs and notes remain useful; a food database is not the same as meal-consumption history.
* A request for 1,000 treatments returned 213 spanning September 5–8. This does **not** establish total historical retention: v1 default date filtering may limit responses. Backfill must use explicit date windows.

These observations must be refreshed by the implementation's connection probe. Configuration observations are historical facts about those records, not guaranteed current settings.

### Unknowns with prescribed handling

1. Autosens enablement, profile-percentage automations, insulin plugin/peak/DIA, and current profile activation history: discover from timestamped uploads where possible, then show the evidence for user confirmation in onboarding. Unknown is a real state, never false or 100% by default.
2. Historical completeness, particularly SMB, cancelled temp basals, and carbs used to treat lows: compute collection coverage and request confirmation about logging practice. A glucose history alone cannot prove complete insulin or carb history.
3. Personal glucose targets: import and display the AAPS targets; separately let the user confirm report bands. Do not silently substitute population targets for pump settings.
4. Assumed scope is personal adult use. If the intended user is a child, pregnant, or requires a different clinical population policy, keep descriptive features working but do not enable numerical suggestions under the adult validation policy.

## 3. Fixed technology choices

| Layer | Choice | Purpose |
|---|---|---|
| Application | Python 3.12, PySide6 Qt 6 Widgets | Native KDE-compatible UI, accessible desktop controls |
| Charts | pyqtgraph | Local interactive time-series plots without a browser |
| Contracts | Pydantic 2 strict models | Validated messages and persisted analysis documents |
| HTTP | httpx, synchronous client in worker threads | Explicit timeouts, testable read-only integration |
| Persistence | Python sqlite3, numbered SQL migrations | Transactional local storage; no database server |
| Numeric analysis | NumPy, SciPy | Deterministic metrics and sensitivity analyses |
| Secrets | Secret Service via Python keyring, integration-tested in Flatpak | Desktop secret storage; session-only fallback |
| Inference | Bundled llama.cpp `llama-server`, Vulkan plus CPU build | App-managed local inference |
| Model | Official Qwen/Qwen3-14B-GGUF, Q4_K_M | Initial English explanation model; not a medical authority |
| Distribution | Flatpak, application ID `io.github.bganalyzer.BGAnalyzer` | Bazzite installation without RPM layering |
| Tests | pytest, pytest-qt, Hypothesis, respx | Numeric, UI, property, and HTTP tests |
| Development | uv lockfile; Ruff; mypy; CMake/Ninja for llama.cpp | Repeatable builds |

Use standard library zoneinfo; package tzdata for consistent historical timezone behavior. Use Decimal for imported profile/dose quantities and rounding; float64 for statistical arrays. No JavaScript or Node runtime in the shipped app. The AAPS algorithm is ported as described below rather than calling a separate OpenAPS shell installation.

Resolve exact compatible Python dependency versions once in work package W01 using Python 3.12 and commit `uv.lock`; never use unbounded dependencies at release. Set direct requirement ranges to the selected minor series. In `provenance/dependencies.json` record Python, Qt, runtime/SDK, compiler, Mesa test version, model revision, algorithm revision, and app commit. An implementer must obtain real hashes from downloaded bytes; never invent checksums to fill this specification.

## 4. Repository structure and dependency boundaries

```text
pyproject.toml
uv.lock
README.md
IMPLEMENTATION_PLAN.md
LICENSE
THIRD_PARTY_NOTICES.md
src/bganalyzer/
  __main__.py                 # QApplication and AppController construction
  app.py                     # lifecycle, single instance, workers, shutdown
  contracts/                 # domain.py, analysis.py, inference.py
  config.py                  # versioned nonsecret settings
  secrets.py                 # keyring/session-only credential provider
  db/                        # connection.py, repository.py, migrations/*.sql
  nightscout/                # client.py, probe.py, v1.py, v3.py, sync.py
  normalize/                 # glucose.py, treatments.py, profile.py, device.py
  timeline/                  # profiles.py, insulin.py, contexts.py, quality.py
  analytics/                 # metrics.py, episodes.py, patterns.py, comparison.py
  autotune/                  # models.py, insulin.py, iob.py, prep.py, core.py
  recommendations/           # eligibility.py, candidates.py, evidence.py, lifecycle.py
  inference/                 # manager.py, download.py, prompt.py, validate.py
  ui/                        # main_window.py, onboarding.py, pages/, models/
  export/                    # report.py, bundle.py
resources/                   # icons, prompt templates, explanation templates
models/catalog.json          # approved revision/file/size/hash/license metadata
packaging/flatpak/            # manifest, desktop file, metainfo, launcher
scripts/                     # fetch-source, build-llama, verify-model, release-check
tests/
  unit/ integration/ ui/ property/ parity/ fixtures/synthetic/
reference/aaps-harness/       # JVM-only development reference runner, not shipped
provenance/                  # upstream source manifest and algorithm map
docs/                        # protocol findings, support matrix, validation report
```

Dependency direction: UI → application services → contracts/repositories/analysis. Analysis has no Qt, network, database, or model dependency. Inference receives only EvidenceBundle objects and cannot call Nightscout, modify recommendations, or read arbitrary files. Nightscout client exposes GET operations only. Do not add a general agent/tool framework.

Process model: one GUI process; one dedicated sync QThread using httpx; one analysis subprocess launched with `multiprocessing` spawn; one app-owned llama-server child. Qt widgets are touched only on the main thread. Each database thread/process owns its connection. Serialize writes in the application repository worker; analysis returns results for transactional persistence. Take a consistent SQLite read transaction or immutable snapshot for each analysis run; never mix revisions while a sync is committing.

## 5. Local storage and migrations

Use QStandardPaths AppDataLocation, AppConfigLocation, and CacheLocation. Under Flatpak these resolve inside its per-app data directory; do not hard-code `/home/proot`. Create private directories mode 0700 and private files mode 0600. `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000`. Use parameterized SQL only. Back up the database before a migration, test migration on a copy, and roll back startup to a recoverable error if migration fails.

Minimum schema below is normative. `*_ms` means signed INTEGER UTC Unix milliseconds. JSON is canonical UTF-8 with sorted keys. IDs are UUIDs except source record IDs, which remain opaque strings. Money-like exact dose/profile decimals are persisted as TEXT, not binary float. Numeric chart/query columns may additionally store REAL derived values.

| Table | Columns and constraints |
|---|---|
| `schema_version` | `version INTEGER PRIMARY KEY`, `applied_ms INTEGER NOT NULL` |
| `sources` | `id TEXT PRIMARY KEY`, `origin TEXT UNIQUE NOT NULL`, `api_mode TEXT`, `server_version TEXT`, `capabilities_json TEXT NOT NULL`, `created_ms INTEGER` |
| `sync_state` | `(source_id, collection) PRIMARY KEY`, `cursor_json TEXT`, `backfill_start_ms INTEGER`, `backfill_end_ms INTEGER`, `last_success_ms INTEGER`, `last_error_code TEXT`; source FK |
| `raw_records` | `(source_id, collection, remote_id, revision_hash) PRIMARY KEY`, `event_ms INTEGER`, `server_modified_ms INTEGER`, `first_seen_ms INTEGER`, `payload_json TEXT NOT NULL`, `is_valid INTEGER CHECK IN (0,1)`, `is_current INTEGER CHECK IN (0,1)`; one partial UNIQUE current row per source/collection/id |
| `glucose` | `id TEXT PRIMARY KEY`, source/remote/revision reference, `event_ms INTEGER NOT NULL`, `sgv_mgdl REAL`, `valid INTEGER`, `quality_json TEXT`; UNIQUE source/remote; index event_ms |
| `treatments` | `id TEXT PRIMARY KEY`, source/remote/revision reference, `event_ms INTEGER`, `end_ms INTEGER`, `kind TEXT`, `insulin_u TEXT`, `carbs_g TEXT`, `rate_u_h TEXT`, `percent TEXT`, `delivery_status TEXT`, `pump_event_key TEXT`, `valid INTEGER`, `attributes_json TEXT`; index event_ms and pump_event_key |
| `profile_versions` | `id TEXT PRIMARY KEY`, source/remote/revision reference, `profile_name TEXT`, `effective_from_ms INTEGER`, `timezone TEXT`, `units_original TEXT`, `normalized_json TEXT NOT NULL`, `content_hash TEXT NOT NULL` |
| `profile_activations` | `id TEXT PRIMARY KEY`, `profile_version_id TEXT` FK, `start_ms INTEGER`, `end_ms INTEGER`, `percentage TEXT`, `time_shift_minutes INTEGER`, `origin TEXT`, `evidence_json TEXT`, `certainty TEXT` |
| `device_status` | `id TEXT PRIMARY KEY`, source/remote/revision reference, `event_ms INTEGER`, `configuration_json TEXT`, `loop_json TEXT`, `quality_json TEXT` |
| `annotations` | `id TEXT PRIMARY KEY`, `start_ms INTEGER`, `end_ms INTEGER`, `kind TEXT`, `text TEXT`, `attributes_json TEXT`, `created_ms INTEGER`, `updated_ms INTEGER`, `deleted_ms INTEGER`; app-local only |
| `data_revisions` | `revision INTEGER PRIMARY KEY`, `committed_ms INTEGER`, `affected_start_ms INTEGER`, `affected_end_ms INTEGER`, `reason TEXT` |
| `analysis_runs` | `id TEXT PRIMARY KEY`, `data_revision INTEGER`, `start_ms INTEGER`, `end_ms INTEGER`, `profile_hash TEXT`, `algorithm_version TEXT`, `policy_hash TEXT`, `input_hash TEXT`, `state TEXT`, `metrics_json TEXT`, `created_ms INTEGER`, `error_code TEXT`; UNIQUE input_hash/algorithm_version/policy_hash |
| `evidence` | `id TEXT PRIMARY KEY`, `run_id TEXT` FK, `kind TEXT`, `start_ms INTEGER`, `end_ms INTEGER`, `payload_json TEXT NOT NULL`, `source_refs_json TEXT NOT NULL`, `content_hash TEXT NOT NULL` |
| `recommendations` | `id TEXT PRIMARY KEY`, `run_id TEXT` FK, `family TEXT`, `state TEXT`, `baseline_profile_hash TEXT`, `candidate_json TEXT`, `evidence_ids_json TEXT`, `eligibility_json TEXT`, `created_ms INTEGER` |
| `recommendation_events` | `id TEXT PRIMARY KEY`, `recommendation_id TEXT` FK, `event_ms INTEGER`, `event_type TEXT`, `payload_json TEXT`; append-only local audit |
| `explanations` | `id TEXT PRIMARY KEY`, `run_id TEXT` FK, `evidence_hash TEXT`, `model_hash TEXT`, `prompt_version TEXT`, `validated_json TEXT`, `status TEXT`, `created_ms INTEGER` |

Maintain source-reference tuples on all derived rows. A corrected remote record creates a new raw revision, invalidates/replaces its normalized view, and marks affected analyses stale. Keep old referenced revisions so an older report remains reproducible. A remote tombstone removes the record from current analysis but preserves provenance; user-requested local deletion is different and removes associated content.

Default local retention: 365 days of unreferenced clinical records, configurable to 90 days or unlimited. Records used by saved reports remain until those reports are deleted; explain this in storage settings. This allows longer local history than the server retains. Model files are separate from database backups. Provide export/delete controls; never silently purge on database corruption or storage pressure. Warn at less than 2 GiB available, stop new downloads/imports at less than 512 MiB, retain existing data, and allow export.

Local data is protected by OS account permissions and whatever disk encryption the host uses; SQLite is not encrypted by this design. State that accurately in settings. Do not claim keyring encryption protects the clinical database. An encrypted database can be a later separately tested feature; plaintext secrets are never an acceptable fallback.

## 6. Nightscout connection and synchronization

### Connection and authentication

Onboarding accepts HTTPS origin and optional base path, no embedded username/password, query, or fragment. Reject non-HTTPS except an explicit localhost development mode. Verify certificates. Canonicalize origin; redirects to another origin are rejected without forwarding credentials. Limit JSON body size to 25 MiB/request and fail cleanly on HTML, malformed JSON, or unexpected top-level types.

Probe v1 status, v3 version/status, and one item per required collection. Display capability results separately: readable, forbidden, missing, empty, malformed. Implement v1 first because it was verified readable on this deployment. Add v3 incremental history when authentication and protocol tests pass. API choice is stored per source; a 401 during sync must not silently downgrade authentication.

Authentication choices: public read, access token, or legacy API secret. Default to a dedicated read-only token if authentication is configured. For v1 API-secret mode use the documented SHA-1 digest in the `api-secret` header; do not put the secret in a URL. For v3 token mode implement Nightscout's token-to-JWT exchange and Bearer header using the pinned server contract. Its exchange URL can contain credential material: disable URL logging there and strip credentials from exceptions, proxy traces, and support exports. JWT stays in memory and refreshes on expiry, with one refresh attempt on 401. Never treat an arbitrary user secret as a JWT.

Store the credential with the desktop Secret Service keyed by normalized origin and app ID. If unavailable/locked, offer unlock or session-only entry; do not silently write an `.env` or settings file. The credential supplied during planning is not part of the product defaults.

### Read-only transport policy

`NightscoutClient` has `get_status`, `fetch_window`, `fetch_profiles`, and `fetch_history` methods, no arbitrary request method. Enforce GET in its transport wrapper as defense in depth. Tests must reject POST/PUT/PATCH/DELETE to the Nightscout origin. The localhost model client is a different class and may POST inference requests. Reports and local annotations never become Nightscout treatments.

### Required collections and fields

| Collection | Consumption |
|---|---|
| entries | `date` epoch ms, `dateString`, `sgv`, `type`, validity, device, source ID |
| treatments | timestamps, eventType, validity, insulin, carbs, isSMB, temp-basal rate/duration, cancellation IDs, profile switches, targets, notes, bolus calculator data |
| profile | all stores and historical versions; basal/carbratio/sens/targets/DIA/timezone |
| devicestatus | timestamped AAPS configuration, available enacted/suggested/IOB/COB/ratios; suggested commands are not delivery evidence |
| food | optional catalog only; never turn catalog entries into consumed carbs |

Preserve unrecognized fields in raw JSON. Record unknown event types for inspection; never discard their potential insulin relevance silently.

### Initial v1 backfill

1. Establish `T0` from local UTC clock; compare server clock and expose differences above 120 seconds. Request 90 days ending T0 plus insulin lookback `DIA + 2 hours`; unresolved DIA blocks tuning, not download.
2. Fetch profiles before treatment interpretation. Request historical records explicitly; a single latest profile is insufficient. Fetch one predecessor profile before the analysis start if available. No predecessor means the early profile timeline is unknown.
3. For entries issue explicit half-open windows using `find[date][$gte]=start_ms`, `find[date][$lt]=end_ms`, `count=1000`. Build query dictionaries with httpx; never hand-concatenate credentials.
4. For treatments and devicestatus use documented `created_at` window filters with ISO UTC timestamps and `count=1000`, then normalize true event time. Use the pinned v1 schema/tests to detect a server that ignores filters. For profiles use its supported date fields and list pagination, verified in W02.
5. Start with one-day windows. If a response reaches the requested limit, or shows a lower server cap, subdivide the interval and deduplicate by source ID. Discover actual caps during probe. Never advance past a possibly truncated window. At a one-millisecond unresolved interval, use verified ID pagination or mark that window incomplete and stop; never drop equal-time records by incrementing the timestamp.
6. Commit each complete window and its checkpoint in one transaction; interrupted downloads resume there. Synchronize newest seven days first for an early dashboard, then older windows. Mark the dashboard as partial until complete.
7. Track earliest/latest retrieved event, empty intervals, and requested bounds per collection. "90 days requested" and "90 days available" are separate labels.

### Incremental sync

While running, poll every 60 seconds with ±10 seconds jitter; allow Refresh now. Use maximum two simultaneous network requests; default sequential backfill. Timeouts: connect 10 seconds, read 30 seconds, write 10 seconds, pool 5 seconds. Retry connection errors, 429, and 5xx with 5/15/60/300 seconds backoff plus jitter; honor bounded Retry-After up to one hour. Do not repeatedly retry 401/403; show actionable authentication state.

In v1 mode re-fetch the latest 48 hours on each cycle using window caching/ETags only where verified. Reconcile the last seven days daily and full retained remote history weekly to catch older edits. Absence from a v1 window is not automatically a deletion: distinguish server retention, query behavior, and actual invalidation; mark unresolved disappearance and suppress affected candidates. State that v1 does not guarantee an immediate deletion feed.

In v3 mode use server-modification history cursors, not event timestamps, and handle `isValid=false`. Pin the deployment's OpenAPI contract. Read collection history in pages and advance a durable cursor only after the complete modification boundary has been committed; repeated timestamps require overlap/deduplication or verified tie pagination. If the server cannot fully paginate an equal-timestamp boundary, stop that collection with `INCOMPLETE_PAGE_BOUNDARY`. Test identical modification timestamps, late edits, deletion, restart, and no changes. Do not invent query operators from this prose: capture accepted operators from the pinned Swagger in W02 and document requests/responses with synthetic fixtures.

On suspend/resume perform one catch-up sync; do not replay missed timer ticks. On exit cancel requests and commit/rollback before closing SQLite. No background service when the app is closed. Offer explicit start-at-login and minimize-to-tray preferences, default off. Desktop sleep still suspends monitoring; show this in the connection page.

## 7. Normalization and time semantics

Represent glucose internally in mg/dL; UI defaults to mmol/L. Convert display using mg/dL ÷ 18 and ISF using the same factor. Retain original units and values. Profile IC is grams/unit, basal units/hour, bolus units; percentages have a distinct type. Reject nonfinite values and ambiguous units rather than guessing from magnitude. Glucose threshold comparisons happen in internal units before display rounding.

Use event timestamps, not ingestion timestamps, for analysis. Precedence: collection-defined numeric event timestamp, explicit ISO event timestamp, documented created_at fallback. Numeric timestamp units are defined by the field adapter, not a generic length heuristic. If two event timestamps disagree by more than 60 seconds, flag the record; quarantine it from tuning until resolved. Naive timestamps require a documented source timezone or are unknown.

Store UTC; group and label according to the historical profile timezone. Display Europe/London by default. Profile schedule lookup uses local wall time at each UTC instant. On the autumn clock change the repeated hour has two different UTC intervals, both valid; spring's missing hour has no elapsed duration. Integrate elapsed UTC seconds. Do not assume every day is 24 hours. If AAPS reference behavior differs on a DST transition, retain that documented behavior for parity but exclude the transition analysis day from numerical suggestions until validated.

Glucose: only valid SGV records enter CGM metrics; meter/calibration records are separate. Do not manufacture a reading from error/sentinel codes. Resolve duplicate identical source records by ID/revision. Distinct sensors at the same timestamp with disagreeing values are ambiguous, not averaged automatically. Show questionable points; exclude documented invalid codes from analysis. Do not suppress physiologically extreme but valid readings as mere outliers.

Treatments: normalize delivered insulin, carb entries, calculator events, temp basals, cancellations, suspensions, extended boluses, profile switches, targets, site/insulin changes, exercise, and notes into explicit kinds. `isSMB=true` overrides the Meal Bolus label. A missing SMB flag means bolus subtype unknown. Calculator proposals and `openaps.suggested` are never counted as delivered insulin. Same pump identity/event ID with identical semantics is one delivery; multiple genuine small boluses near the same time remain separate. Conflicting duplicates block that interval. Carbs on calculator and treatment records need source-identity matching; temporal proximity alone is not proof of duplication.

Local annotations can add meals, rescue carbs, exercise, alcohol, illness, stress, or uncertain delivery periods. They have their own provenance, never overwrite imported facts, and are removable. Any annotation edit invalidates affected evidence. Explicitly distinguish "not recorded" from "did not happen".

## 8. Reconstructing profiles and insulin delivery

Produce immutable `ProfileTimeline` and `DeliveryTimeline` services. APIs:

```python
resolve_profile(at_ms: int) -> ResolvedProfile | UnknownProfile
resolve_delivery(start_ms: int, end_ms: int) -> list[DeliveryInterval]
build_analysis_snapshot(start_ms: int, end_ms: int, revision: int) -> AnalysisSnapshot
```

`ResolvedProfile` includes source profile ID/hash, basal/IC/ISF/target values at that instant, timezone, percentage, time shift, activation evidence, and whether the imported profile is already customized. Port AAPS customization semantics from the pinned profile implementation and test against it. Never apply a percentage twice to an already-effective profile. A profile-store upload is not necessarily activation of that profile; a name or `defaultProfile` alone does not prove active history.

`DeliveryInterval` has `[start_ms,end_ms)`, U/h, origin (`reported_temp`, `scheduled_assumed`, `reported_suspend`, `unknown`), source IDs, and quality. Build boundaries at every profile transition, basal-schedule transition, temp-basal start/end/cancellation, suspension/resume, and pod change. An explicitly cancelled temp stops at cancellation, not its original planned end. Overlapping replacements use confirmed pump event ordering; unresolved ties are unknown. Percentage temp basals resolve against the effective schedule at each boundary. Persist absolute-vs-percentage semantics in the adapter and test from source fixtures; do not infer a 0 percent field means a zero absolute rate without that mapping.

When no temp basal is recorded, scheduled delivery is only an assumption. Confirm upstream upload completeness and pump-running status where available; source gaps, offline periods, and unknown cancellation histories block numerical use. Never convert missing data into zero insulin. Integrate interval insulin as `rate_u_h * elapsed_seconds / 3600`. Suspended intervals are zero only when suspension is established. Boluses and SMB are discrete delivered units; device suggested/enacted commands alone cannot be treated as independent extra doses. Extended bolus support requires confirmed delivered/cancelled portions; otherwise exclude affected days.

Maintain separate scheduled basal, estimated delivered basal, and bolus/SMB series. A loop's additional delivered insulin is not itself proof that the programmed basal should increase: meals, targets, autosens, and residual insulin may explain it.

For historical IOB and activity, port AAPS LocalInsulin and AutotuneIob semantics; do not use a linear decay or brand-based fixed duration. Resolve the effective insulin plugin/DIA/peak from timestamped config and confirmation. Load `DIA + 2 hours` before each analysis boundary. Distinguish total delivered-insulin IOB from AAPS net-basal IOB; parity tests must specify which quantity is compared. Uploaded IOB is a comparator when available, never blindly mixed with a differently defined reconstructed IOB. Missing uploaded IOB does not automatically block analysis if reconstruction is validated and all delivery inputs are complete; missing inputs do.

## 9. Descriptive metrics and recurring patterns

These features work before numerical suggestions and without an AI model.

### Report metrics

Default 14 completed days; selectable 7, 30, 90 days and custom range. Use the user's confirmed report bands. Offer standard adult reference bands (54, 70, 180, 250 mg/dL) as labelled reference metrics, separately from AAPS targets; they are not instructions to change targets. See the ADA source in section 22 for individualized goals.

For dashboard time metrics assign each valid reading `[timestamp, min(next_valid_timestamp,timestamp+5 minutes,window_end))`. Leave gaps uncovered; no carry-forward beyond five minutes. Clip at report boundaries. TIR/TBR/TAR use covered duration as denominator; report coverage against total elapsed duration beside them. Compute duration-weighted mean and population SD on the same intervals, CV = 100 × SD/mean when mean > 0. Make all buckets disjoint: `<54`, `[54,70)`, `[70,180]`, `(180,250]`, `>250`; configurable bands use the analogous exhaustive partition. Sum must be 100% within floating tolerance when coverage > 0. No coverage means null, not zero.

For the daily overlay show 5th/25th/50th/75th/95th percentiles in 30-minute local-time bins, each day's bin median contributing at most one observation; require five distinct days per shown percentile bin. Display sample count and coverage; no line bridging bins without support. Label as a daily percentile overlay, not a certified AGP implementation.

For meal episodes use confirmed carb events; group entries within 20 minutes only for visualization while retaining original event identities. Show glucose from 60 minutes before to 6 hours after, all boluses/SMB/temp basals, premeal baseline median over the preceding 15 minutes, observed peak, time-above-range, and glucose at +2h/+4h when a reading exists within ±5 minutes. Overlapping meals and rescue carbs are labelled. Missing readings remain null. Food notes do not establish fat/protein content or exact carb quantity.

Compute daily recorded insulin totals only where coverage allows; otherwise show recorded subtotal and missing intervals. Show annotations, offline periods, temporary targets, site changes, and profile changes on every evidence chart.

### Pattern rules, version `patterns-v1`

Rules create descriptive findings, not dose calculations:

* Repeated low episodes: at least three distinct local days with valid BG below the selected low band for at least 15 covered minutes in the same two-hour clock bucket. A gap over five minutes breaks continuity. List every contributing and conflicting day. The 3-day/15-minute rule is a product grouping heuristic, not a treatment threshold.
* Repeated postmeal elevation: at least five usable meal episodes on at least three days in the same four-hour meal-time bucket, with the median proportion above the selected high band during minutes 60–180 exceeding 50%. Include premeal values, insulin timing, and context. Never conclude IC is the cause from this rule alone.
* Repeated loop compensation: same two-hour bucket on at least five days with nonzero net temp-basal delivery in a consistent direction on at least 80% of usable days. Describe the observed compensation and confounders; do not convert average extra delivery into a basal recommendation.
* Data-quality findings: stale data, missing delivery, unresolved profile, ambiguous units, insufficient carb context, and config changes. These take precedence over suggestion generation.

Store rule version, thresholds, exact source IDs, episode summaries, all exclusion codes, and contradictory examples. Sort findings by low-glucose evidence, data quality, then other patterns. No undocumented "AI confidence" percentage.

## 10. Numerical engine: pinned AAPS Autotune port

### Why this engine and what it does not establish

Use AAPS's existing deterministic Autotune implementation as the numerical starting point. It is a reproducible engineering reference, not proof of clinical suitability. An observational closed-loop record cannot uniquely identify basal, IC, and ISF errors in all circumstances. Keep an explicit abstention state.

AAPS Autotune computes hourly basal and scalar IC/ISF adjustments. It does not independently estimate each circadian IC/ISF segment. Preserve that limitation in data contracts and UI. Dynamic ISF requires a separate supported analysis policy; v1 does not tune DynISF adjustment factor or recommend enabling/disabling it. [AAPS Autotune documentation](https://androidaps.readthedocs.io/en/latest/AdvancedOptions/Autotune.html), [Dynamic ISF documentation](https://androidaps.readthedocs.io/en/latest/DailyLifeWithAaps/DynamicISF.html).

### Exact reference

Repository: `https://github.com/nightscout/AndroidAPS`.
Tag observed: `3.4.2.1`.
Resolved commit: **`1393357107a2b27ba153df31d64e745efd771ef2`**.

Port from the following prefix:
`plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune/`

| Reference file/function | Python destination |
|---|---|
| `AutotuneCore.kt::tuneAllTheThings` | `autotune/core.py::tune_day` |
| `AutotunePrep.kt::categorize`, `categorizeBGDatums` | `autotune/prep.py::categorize_day` |
| `AutotuneIob.kt` input initialization, temp splitting, conversion and IOB | `autotune/iob.py` plus verified timeline adapter |
| `data/LocalInsulin.kt::iobCalcForTreatment` | `autotune/insulin.py::iob_for_treatment` |
| `data/ATProfile.kt`, BGDatum, CRDatum, PreppedGlucose, deviations | `autotune/models.py` |
| `AutotunePlugin.kt` day boundaries and iteration order | `recommendations/candidates.py` |

Also inspect the pinned `plugins/insulin/.../InsulinOref*Plugin.kt`, profile customization implementation, and `plugins/aps/src/test/.../autotune/` reference tests. Record every copied/translated file, upstream SHA-256, source line mapping, and license notice in `provenance/aaps-port.json`. Use an AAPS-license-compatible license and preserve notices; W01 checks the actual pinned license before selecting the repository license.

No re-deriving the algorithm from descriptions, no replacing it with `1800/TDD`, no fasting-BG slope shortcut, no heuristic carb-dose formula, and no asking the LLM for profile numbers. Translate branching, ordering, windowing, rounding, missing-data behavior, caps, UAM classification, and insulin curves literally first. Specifically preserve AAPS's ordering and rounding rather than Python's default rounding where they differ. Characterize any reference bug explicitly; a bug fix becomes a separately versioned deviation with its own tests, never a silent "cleanup".

### Contracts and orchestration

```python
class AutotuneInput:
    snapshot_id: str
    baseline_profile: ATProfile
    analysis_days: list[LocalAnalysisDay]
    insulin_configuration: InsulinConfiguration
    settings: AutotuneSettings

def categorize_day(day: DayInputs, profile: ATProfile) -> PreppedDay: ...
def tune_day(prepped: PreppedDay, previous: ATProfile, baseline: ATProfile) -> TunedDay: ...
def run_autotune(inputs: AutotuneInput) -> AutotuneRun: ...
```

Use the pinned plugin's analysis-day boundary, timezone treatment, and chronological day order, extracting exact behavior in W06 rather than assuming midnight. Default lookback is 14 completed analysis days; support 7–30. Select only days within a stable, resolved configuration/profile epoch. Initialize `previous` to a deep copy of the real baseline at the beginning of every run. For each eligible day, build IOB inputs, categorize, tune with the same immutable baseline for algorithm bounds, and set previous to that day's output. Never feed yesterday's proposed settings back as today's actual settings. Store every intermediate day and contribution.

Disable tuning DIA, insulin peak, targets, safety limits, DynISF factors, and automations. Preserve existing values. Import algorithm autosens bounds from confirmed AAPS configuration; unknown bounds block numeric output instead of using library fallback values silently. Set UAM-as-basal preference false in the app policy, while documenting and testing the pinned algorithm's actual classification behavior: this flag is not a guarantee that all UAM is excluded. Show reclassified UAM contributions and suppress candidates if unexplained absorption affects the relevant support.

For scalar baseline IC/ISF show scalar candidates. For multi-segment IC/ISF, default to an overall research estimate plus segment-specific descriptive evidence; do not flatten the user's schedule. A uniformly scaled schedule may be displayed only under the explicitly validated `circadian_scale` policy matching pinned ATProfile semantics. Label it "same proportional adjustment across existing segments; segment shape not independently fitted". Until that policy passes validation, multi-segment IC/ISF receive no manual-entry numeric proposal. Basal support is independently assessed but can still be blocked by unsupported confounding.

### Numerical parity requirement

Create a development-only Kotlin/JVM harness around the unchanged reference numerical classes. Replace Android logging/preferences/database access with injected deterministic fixture interfaces; do not rewrite reference math. Feed the same normalized synthetic dataset to the harness and Python port. Cover insulin curves, negative net basal, SMB, exclusions, day boundaries, scalar and circadian profiles, and iterative runs. If a harness dependency cannot be isolated without semantic change, run the reference test in the pinned AAPS development test environment and check in its synthetic outputs plus generator provenance.

Compare classification membership and record IDs exactly; compare rounded output decimals exactly; intermediate float values within absolute 1e-8 plus relative 1e-7 unless source explicitly rounds earlier. Any looser tolerance requires an explained source-level reason and review. A passing final profile with different input classification is not parity.

## 11. Eligibility and candidate policy

All thresholds below are explicit engineering selection rules, **not validated medical safety guarantees**. They are stored in `policy-v1.json`, included in report provenance, and subject to section 18 validation. Do not label a candidate safe because it passes them.

Compute `EligibilityResult {status, reason_codes[], evidence_ids[], supported_families[]}` before running numerical display. Status is one of `eligible`, `insufficient_data`, `unsupported_configuration`, `unresolved_history`, `stale`, `validation_unavailable`.

Required for any numerical candidate:

1. Current connection record is fresh enough to establish configuration and profile; BG age ≤15 minutes and no known newer config mismatch. Older complete reports remain viewable but marked historical; they are not current manual-entry suggestions.
2. At least seven eligible completed analysis days in the requested lookback, within one compatible configuration epoch. Each day has ≥90% covered CGM duration, no CGM gap >20 minutes within a contributing episode, and complete verified treatment backfill plus resolved delivery/profile history including insulin lookback. These are separate checks; high CGM coverage cannot offset missing insulin.
3. Insulin plugin/DIA/peak, profile activation/customization, SMB labeling and delivery semantics are supported. Autosens mode is known and included in the reference compatibility matrix. Unknown mode abstains. If enabled, replay uses the pinned Autotune semantics; it does not multiply observed ratios onto profile values again.
4. All contributing days have explicit user confirmation that meals and rescue carbs were recorded to the best of their knowledge. Mark this user-reported completeness, not machine verified completeness. Suspected unexplained absorption and contradictory notes still block implicated candidates.
5. Dynamic ISF is off for the candidate epoch. Dynamic ISF on or unknown remains descriptive-only in v1; do not recommend static ISF changes as a replacement for it.
6. No unresolved duplicate dosing, unsupported extended bolus, insulin-source mismatch, offline delivery gap, or ambiguous historical profile touches contributing windows.
7. Exclude days with user-marked illness, steroids, major unusual exercise/alcohol, or delivery failure. Include the reason and evidence; this exclusion is a policy heuristic. Site changes alone are annotations, not automatic evidence of failure. Temporary targets and percentage overrides require supported reference behavior; unsupported changes exclude their day plus required insulin carryover.
8. No unobserved/reported profile change awaiting confirmation, and enough eligible days after the last confirmed change to satisfy the same seven-day minimum. Do not stack unimplemented suggestions.

Per-family support: basal hour needs relevant basal-classified observations on at least five distinct days; scalar IC needs at least five complete supported carb episodes on at least three days; ISF needs at least five independent reference-defined correction episodes on at least three days. Define independent episodes as nonoverlapping insulin-action windows, not adjacent CGM points. If the reference cannot provide identifiable correction episodes, withhold numeric ISF and show that limitation. Do not substitute 5 glucose readings for 5 episodes.

Run leave-one-day-out sensitivity: repeat the complete algorithm excluding each included day, with the original baseline and chronological order. For a proposed parameter, every supported rerun must move in the same direction as the full run; if any returns no support, crosses baseline, or is invalid, mark unstable and withhold that parameter. Store min/max rerun values as **sensitivity range**, never a confidence interval or predicted outcome range.

An increase in insulin exposure (basal up, IC down, ISF down) is withheld when contributing support windows include a validated low episode or any valid BG <54 mg/dL, pending diabetes-domain review. Include the contradicted hypothesis in the report. Reductions do not bypass other eligibility rules. No automatic "reduce by X%" rescue rule exists.

Before manual-entry display, require a `RecommendationPolicy` with validated allowable change bounds, valid population/modes, rounding/entry increments from the supported AAPS/pump integration, and policy version. This plan deliberately does not invent medically safe percentage caps. Until a reviewed policy exists, show deterministic pattern evidence and developer parity output separately; do not expose unvalidated numbers as actionable suggestions. The implementation of policy validation is fully specified: schema-required fields, positive finite bounds, baseline-relative comparisons per family, reject rather than clamp when exceeded, and an auditable validation record. No LLM may populate or approve this policy.

Quantize eligible candidates to validated entry increments with Decimal; choose the representable value closest to baseline that does not exceed the unrounded proposed change. If equal to baseline, report no representable change. Re-run all bounds after quantization. List hourly basal changes with original segment coverage; preserve boundaries or explicitly show newly introduced ones. Show total scheduled daily basal before/after for a standard 24-hour schedule, distinctly from actual DST-day delivery. Do not claim an anticipated TIR improvement from this calculation.

The UI may show all families for comparison, but must explain that combined profile effects interact. There is no automatic schedule for applying several changes and no assertion that independent recommendations can safely be combined.

## 12. Evidence and explanation contracts

Use strict Pydantic models with `extra='forbid'`, finite-number validation, UTC timestamp types, and explicit units. Serialize a JSON Schema for each to `resources/schemas/`; CI checks examples against them.

`EvidenceBundle` contains:

* run ID, input hash, data revision, algorithm/policy versions, analysis window and timezone;
* baseline profile hash and activation evidence;
* metrics with numerator, denominator, units, sample/day count and coverage;
* candidate objects `{id, family, segment, baseline_value, raw_value, display_value, unit, direction, status, reason_codes}`;
* contribution objects `{id, candidate_ids, source_refs, interval, category, input_values, intermediate_values, formula_or_reference_step, output_contribution}`;
* exclusions with source refs and reason codes;
* contradictory episodes and sensitivity reruns;
* contextual annotations labelled imported, user-confirmed, or unverified;
* limitations, including missing fields and unsupported features.

Evidence IDs must identify immutable stored objects, not unstable row positions. Clicking one opens its glucose/insulin/meal chart and ledger. Raw record inspection is local and optional; redact device serials from default display and export. Never include credentials, personal hostname, pump serials, or uploader identity in the model prompt.

Default recommendation detail layout, in order:

1. Status and baseline profile date; candidate if eligible, or the exact reason it is withheld.
2. Before/after with units and plain-language direction. IC/ISF down means more insulin for the same calculation inputs; avoid saying "lower sensitivity" ambiguously.
3. Deterministic calculation ledger: baseline → supporting days/episodes → reference algorithm intermediate steps → raw result → policy checks → representable candidate.
4. Supporting observations, with timestamps and direct chart links.
5. Contradictory observations and alternative explanations.
6. Missing/excluded data and sensitivity range.
7. User action: save report, mark discussed, dismiss, or record a change made elsewhere.

A clinical narrative is not a causal proof. Language must say "consistent with" or "the calculation used" when inference is observational. Do not say a meal or incorrect setting caused an event merely because they co-occurred.

## 13. Local inference lifecycle and model handling

Bundle llama.cpp as a child process for crash isolation. The GUI starts it on first explanation request and terminates it on exit; the user sees one application. Initial verified source revision for evaluation: **`9cf3bf256b5a50a971a636c36dfe974387140687`**. Pin this or a deliberately reviewed replacement in provenance; do not build floating master for releases.

Build Vulkan server with CMake options `-DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF`; build a CPU variant with Vulkan off. Build `llama-server` and package its needed libraries inside `/app`. The app downloads weights itself; runtime remote fetching is disabled. Validate options against the pinned build and capture `--help` in build artifacts. [llama.cpp build documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md).

State machine: `not_installed → downloading → verifying → ready → starting → running → stopping → ready`; failures have typed recoverable states. A cancelled download keeps `.partial` only for a validated resumption. Verify file size and SHA-256 before atomic rename. Resume using HTTP Range only when ETag/revision still matches. Corrupt or unexpected files never launch. Check free space for download plus temporary overhead before starting.

Model catalog specifies official repository **Qwen/Qwen3-14B-GGUF**, immutable revision, exact Q4_K_M file(s), SHA-256, byte length, license identifier/text link, expected context format, and tested runtime hash. Discover whether the chosen revision uses one or multiple GGUF shards; verify every shard. Do not guess filenames. Ship a small app with first-run in-app weight download or local GGUF import; offer an offline distribution bundle containing the same verified weights. No health data is sent to the model host. [Official model card](https://huggingface.co/Qwen/Qwen3-14B-GGUF).

Initial settings: context 8192 tokens, one concurrent request, generation cap 1500 tokens, deterministic evidence selection, temperature 0.2. Disable thinking using the pinned model's supported chat-template setting; never rely on a text suffix alone without a compatibility test. Qwen is used for explanation, not its own dosage calculation. The 14B quantized model is a hardware-informed starting choice, not a measured performance guarantee on this host.

At startup enumerate llama.cpp devices, select the RX 7900 XTX by runtime-reported identifier, and retain the selection. Do not assume device 0: this host has an integrated AMD GPU too. Use available GPU layers initially; if allocation fails, reduce offload once, then offer CPU mode. Do not repeatedly crash and reload. No ROCm installation requirement. Idle-unload after ten minutes by default to release resources for other applications; configurable in settings.

Bind to **127.0.0.1** on a dynamically selected port. Use a cryptographically random per-launch API key loaded through a private file if supported by the pinned server; never put it in logs. Spawn via argument array, no shell. Retry up to three ports if binding fails; readiness must verify authenticated health and expected process/model identity, not merely an open port. Disable web UI and unused endpoints where supported. No CORS wildcard. All requests have bounded timeouts; cancel generation when a user navigates away or cancels.

Launch in an owned process group. On close send graceful terminate, wait up to five seconds asynchronously, then kill only the owned group if necessary. Use parent-death handling in the launcher where available; integration-test GUI crash cleanup. Never kill a user's unrelated llama-server process by name. Keep an app-instance lock so reopening focuses the first window.

### Prompt and response

Input is bounded structured evidence, not 90 days of raw CGM or a vector database. Select up to 20 representative supporting episodes, 10 contradictory episodes, and all blocking limitations deterministically; include full counts and expose all records in UI. If token budget is exceeded, drop optional sample detail before limitations. Limit notes to 1,000 characters each and label them untrusted data; prompt injection inside meal notes cannot supply instructions.

System template: explain only supplied evidence, distinguish association from cause, reference evidence IDs, preserve uncertainty, never invent settings or measurements, do not offer current dosing instructions. No model tools, file access, web access, or executable response actions.

Require JSON `{summary, observations:[{text,evidence_ids}], alternatives:[...], limitations:[...]}` under a schema. Candidate values and numeric calculation tables are rendered by deterministic UI templates, not generated prose. Reject unknown IDs, missing limitation coverage, unsolicited recommendations, and numeric claims not present in the cited evidence. Grammar/JSON validity alone is not factual validation.

Prefer the model to choose evidence IDs and explain relationships without new numeric literals. Validate every rendered number against cited typed fields; wording outside deterministic templates must not introduce new dosage amounts or change directions. If unsupported text remains, discard it. One bounded regeneration is allowed; then show a complete deterministic template report. A model failure never hides findings or blocks export. Cache by evidence hash, model hash, and prompt version; no claim of bitwise reproducible GPU text.

Local chat, if included after core delivery, is limited to questions about a selected report. It uses the same evidence/schema restrictions, cannot alter candidates, and returns "not available in this report" when appropriate. It is not a general-purpose diabetes advisor.

## 14. UI specification

Native Qt main window with left navigation: Overview, Timeline, Meals, Profile Review, Reports, Data Quality, Settings. Keyboard navigation, accessible names, visible focus, scalable text, and color-independent labels are required. Use the system light/dark theme. Avoid a webview.

**Onboarding:** connection/auth → collection coverage → detected AAPS configuration and confirmation → units/timezone/report bands → logging completeness and context → model download/location → initial backfill. Every step is resumable. Model download does not block charts. Show observed configuration timestamps. If user cannot confirm a setting, save unknown and continue descriptive mode.

**Overview:** latest BG with timestamp/age, source status, selected-range coverage and metrics, highest-priority findings, and analysis status. Do not display a stale BG as "now". BG older than 15 minutes is stale; show its actual age and suppress current suggestion status. No dosing action buttons.

**Timeline:** linked glucose, scheduled/estimated-delivered basal, bolus/SMB, carbs/notes, targets, profile changes, offline periods, and quality overlays. Hover shows exact timestamps, units and provenance. Brush-select an interval and open evidence. Invalid records are inspectable but visually distinct. Never connect a CGM line across gaps >10 minutes.

**Meals:** episode table with date/time, recorded carbs, available notes, insulin timing, postmeal metrics, confounders, and completeness; linked overlay chart. Add local notes through a dialog with event time and optional duration. Manual text is never interpreted as verified nutrient grams.

**Profile Review:** baseline schedule and candidate comparison; supported/unsupported families clearly labelled. Each candidate opens section 12 detail. Data insufficient is a first-class result with concrete missing inputs, not an empty spinner. A requested review runs async with cancel/progress. All states work without an LLM.

**Reports:** immutable saved analyses with data/model/algorithm versions; export a local PDF via Qt printing and a machine-readable JSON evidence bundle. Use the file chooser portal. The default export includes summaries and selected clinical evidence, no secrets or device identifiers; an explicit local full-evidence export can include raw medical records. Do not send reports automatically.

**Data Quality:** collection date coverage, gaps, unresolved profiles, unknown event types, current config source/time, v1 limitations, excluded days, and "why no suggestion" codes. Offer re-sync interval and edit local annotations. Show public-read status as factual connection information; do not change server security settings.

**Settings:** Nightscout and credential management, model status/device/storage, synchronization, startup/tray, units/timezone/bands, retention, export/delete, and provenance. Changes to analysis settings invalidate cached results. Never expose a "disable safety checks" switch.

## 15. Recommendation lifecycle and following manual changes

States: `draft`, `withheld`, `ready_for_review`, `discussed`, `dismissed`, `user_reports_applied`, `observed_profile_change`, `superseded`, `stale`. Persist every transition with reason and timestamp. Only eligible validated output enters ready_for_review.

"I changed settings in AAPS" records the user's actual values and time; it does not assume the suggested values were used. Until a matching timestamped active profile arrives, label it unconfirmed. A newly uploaded profile store alone is not activation proof. When activation is established, compare canonical schedule hashes and show exact differences. A different change becomes a new observed baseline, not a successful application of the candidate.

Supersede old ready candidates on active profile/config change, relevant source correction, or policy change. Keep saved reports. Never repeatedly recommend a change calculated from an old profile. Require the same eligible post-change history before another numerical proposal.

Before/after reports use 14 days on each side when available, show actual coverage, profiles, meal/context differences and exclusions, and avoid combining mixed epochs. Compute descriptive TIR/TBR/mean/CV differences; do not attribute improvement causally or show a simulated counterfactual glucose trace as if observed. A trend alert is not a recommendation to reverse settings.

## 16. Failure behavior and security tests

| Failure | Required behavior |
|---|---|
| No internet / server unavailable | Cached charts/reports work; show last sync and freshness; retry backoff |
| Auth expired/forbidden | Pause affected sync, offer credential update, preserve data |
| HTTP success but stale clinical data | Show stale ages independently of last successful request |
| Empty collection | Distinguish empty from forbidden; required missing inputs block tuning |
| Unknown schema/event | Preserve raw record, quarantine relevant interval, show reason |
| Partial history/pagination limit | Do not advance checkpoint or claim complete coverage |
| Model download/VRAM/inference failure | Descriptive and deterministic reports continue; recoverable model state |
| Malicious notes/model output | Treat as data, reject unsupported claims/actions, template fallback |
| Low disk/migration failure | Preserve DB, stop writes safely, offer local recovery/export |
| Clock/timezone/profile ambiguity | Flag exact affected intervals and withhold their tuning |
| GUI crash/restart | Reopen DB safely, resume committed sync, clean up owned child |

No live patient data in tests, commits, screenshots, support logs, CI artifacts or example prompts. Logs contain request category/status/duration and record counts, not URLs with secrets, payloads, pump IDs, glucose values or notes. Add log-redaction tests with a synthetic secret; never use the real supplied credential as a fixture. Network integration tests assert only configured destinations receive clinical requests and the model client stays on loopback.

## 17. Packaging and host acceptance

Use a current supported KDE Flatpak SDK/runtime pair selected and pinned in W01. Build Python dependencies into `/app`; use offline locked wheel sources in the Flatpak manifest. Build llama.cpp inside the same SDK environment. Bundle Qt/PySide6 consistently; do not combine incompatible host Qt plugins with packaged libraries. Record exact runtime branch and source checksums in release artifacts.

Finish arguments: network, Wayland, fallback X11, and DRI device access. Add narrowly scoped Secret Service access if required by the selected keyring integration and test KDE wallet behavior. Use file chooser portals for outside files; do not request full home/host filesystem access, all devices, Bluetooth, or pump access. [Flatpak permissions documentation](https://docs.flatpak.org/en/latest/sandbox-permissions.html).

The release deliverable is an installable `.flatpak` bundle, model catalog, source/license archive, release notes, and checksum manifest. A fresh Bazzite user should install it, launch from KDE, configure Nightscout, and download/import the model entirely through the app. No system Python, Ollama, Node, ROCm, Docker service, or RPM layering is needed. A development container is acceptable for building, not required for end users.

Host acceptance targets are test targets, not measured claims: first window within five seconds excluding first-run model work; 90-day chart navigation interactions below 200 ms after indexing; no main-thread task >100 ms; sync/analysis cancellation feedback within one second. Measure cold/warm model startup, 1,000-token generation, peak RAM/VRAM and CPU fallback on the actual RX 7900 XTX. Choose final offload/batch defaults from those measurements; never fabricate benchmark results. Handle another application consuming GPU memory.

Test KDE Wayland at 100%, 125%, and 150% scaling; light/dark; 1280×800 and 3440×1440. Verify desktop launch, tray opt-in, screen lock, suspend/resume, offline startup, file portal export, keyring locked/unavailable, and no orphan model processes after app exit/crash.

## 18. Validation matrix and release gates

### Required automated tests

1. **Units:** mmol/L/mg/dL and ISF round trips; IC never glucose-converted; basal vs bolus units; zero/nonfinite/negative invalid fields; boundary bucket sums.
2. **Time:** UTC offsets, naive timestamps, London DST both directions, 23/25-hour integration, profile time shifts, event/upload disagreement, clock skew.
3. **Sync:** empty/forbidden/HTML/429/5xx, equal timestamps, server caps, ignored filters, late edits, tombstones, duplicates, crash between page and checkpoint, token refresh, cross-origin redirect refusal, repeated sync idempotence.
4. **Treatment interpretation:** SMB named Meal Bolus, calculator plus actual bolus, genuine repeated boluses, cancelled/replaced temp basal, percentage baseline changes, pod suspension, uncertain delivery, unknown extended bolus.
5. **Profiles:** multiple stores, no activation evidence, already-customized profile, percentage switch, return from temporary profile, edits, missing historical predecessor, mode changes.
6. **Metrics:** hand-computable synthetic intervals, gaps, clipped windows, no data, mixed sensors, valid extreme glucose, meal overlap and missing endpoints.
7. **Reference parity:** literal AAPS tests plus synthetic 7/14/30-day runs; classification and intermediate/rounded outputs; leave-one-day-out runs; original baseline never compounds between app runs.
8. **Eligibility:** every blocking reason exercised individually; contradictory lows, insufficient days, poor carb logging, dynamic ISF, stale configuration, unsupported circadian policy, unvalidated bounds, rounding to no change.
9. **Evidence/LLM:** source IDs resolve, revisions retained, count/denominator correct, invented numbers or IDs rejected, missing caveats rejected, injection in notes inert, model timeout produces complete template report.
10. **Lifecycle:** user-reported settings differ from suggestion, later profile upload without activation, corrected historical data, supersession, restart, no unintended writeback.
11. **Privacy/distribution:** logs/export redaction, only loopback inference, no cloud fallback, model hash mismatch, partial download resume, keyring fallback, packaged CPU/Vulkan startup and exit.

Use synthetic fixtures with explicit expected outcomes rather than snapshotting unexplained giant JSON. Include fixture provenance and generator seeds. Property tests: delivery integrals unchanged by interval splitting; sync idempotence; no duplicate insulin after resync; TIR buckets exhaust covered duration; unit conversion does not change eligibility; removing required evidence cannot strengthen recommendation eligibility.

### Gates

* **G1 — local dashboard release:** W01–W05 and connection/metrics/privacy tests pass. No numerical candidate claims.
* **G2 — numerical engine engineering completion:** W06–W08 parity and provenance pass; unsupported branches demonstrably abstain. Numerical outputs available only in development validation artifacts until G3.
* **G3 — numerical recommendation release:** independent review by a qualified diabetes clinician/domain team of the intended population, source assumptions, AAPS compatibility, bounds, exclusion rules, explanation wording, and representative synthetic/deidentified cases; documented validation methodology and results; prospective observation-only evaluation comparing to clinical review before directing real settings changes. Evaluation never changes pump settings automatically. The sign-off artifact names reviewer/role/date, policy hash, supported modes, cases, acceptance criteria, disagreements and limitations. No fake reviewer or LLM self-approval.
* **G4 — packaged product completion:** all UI flows, offline/failure paths, actual Bazzite host tests, and G3 for any numerical feature labelled available. If G3 is unavailable, ship descriptive mode honestly and report numerical release as outstanding; do not declare the entire requested feature complete.

This is the principal non-code dependency. The implementer can complete the algorithm, comparisons, evidence UI and review package without it, but cannot legitimately claim medical validation from automated tests alone.

## 19. Ordered implementation work packages

Each package must end with the specified artifact and checks. Work sequentially through dependencies; do not begin with an unconstrained chatbot.

| ID | Exact work and output | Completion check |
|---|---|---|
| W01 | Bootstrap Python package, uv lock, Qt window, logging policy, license review, CI, Flatpak skeleton and dependency provenance | Empty app launches in development and Flatpak; Ruff/mypy/tests pass; no host package installation needed |
| W02 | Probe Nightscout v1/v3; pin/capture server API schema; write request/filter/pagination/auth capability contract in `docs/nightscout-contract.md` using synthetic fixtures | Window filters/caps/ties verified; public v1 + forbidden v3 handled; no writes; auth not logged |
| W03 | SQLite migrations, repositories, raw revision retention, sync/checkpoints/backfill/reconciliation | Interrupted/repeated import is correct; 90 days requested with honest per-collection completeness |
| W04 | Units/timestamps/treatment adapters, profile activation and delivery timeline | Hand-checked insulin integrals, duplicate and historical-profile cases pass; unknown states survive |
| W05 | Metrics, meals, annotations, pattern rules, overview/timeline/data-quality UI | G1; synthetic source points drill down correctly; offline UI works |
| W06 | Pin AAPS source, create JVM reference harness, port insulin/IOB/prep/core/day orchestration and rounding | Parity manifest covers all mapped functions; comparison tests meet exact/tolerance rules |
| W07 | Stable epochs, eligibility policy, circadian restrictions, sensitivity reruns, candidate quantization, immutable evidence | Every abstention reason and candidate contribution tested; no unchecked family displayed |
| W08 | Recommendation detail, lifecycle, actual-profile-change detection, report PDF/JSON | All numeric facts come from typed evidence; stale/superseded results cannot be copied as current |
| W09 | Build bundled Vulkan/CPU runtime, verified model catalog/download, lifecycle, keyring and localhost authentication | No Ollama; one-click local explanation; crash/low-memory/download cancellation pass |
| W10 | Constrained explanation schema, validators, evidence selection, deterministic fallback | Invented facts rejected; all limitations visible with model disconnected |
| W11 | Independent validation package and review described in G3 | Explicit approved policy scope or documented outstanding gate; no fabricated completion |
| W12 | Final Flatpak, actual-host performance/UI/failure testing, user help and provenance | G4 for delivered scope; reproducible build/release artifacts and limitations documented |

Implementer progress report after each package: files changed, behavior delivered, tests actually run, unresolved failures, and next package. Do not ask the user to make ordinary library/layout choices already settled here. Ask only for missing personal configuration that cannot be established from dated evidence, or a genuine scope change.

## 20. Definition of done and end-to-end walkthrough

On a fresh Bazzite installation with no Ollama, the user installs the Flatpak and launches it from KDE. They configure their Nightscout URL and, if needed, a credential stored in the keyring. The app shows detected AAPS configuration with timestamps, imports available history, and explains missing collections rather than assuming completeness. A first-use model download occurs inside the app and is integrity-checked.

The user sees glucose, meals, SMB, basal and profile changes together. A review either produces an eligible numerical candidate under the validated policy or a specific supported abstention. Opening a candidate shows the original profile, complete calculation ledger, contributing days, contrary episodes, source records and limitations. Local AI explains those same facts; disabling the model leaves the evidence intact.

No request modifies Nightscout or AAPS. The user records a manual AAPS change, which remains unconfirmed until matching active-profile evidence arrives. The app supersedes prior candidates and later compares observed before/after periods without claiming causation. Closing the app stops its model process. Reopening offline preserves reports. Export works through the native file chooser. Credentials and personal records never enter the source repository.

## 21. Instructions to the implementing LLM

Read this specification and README first. Implement W01 onward and maintain the package completion record. Treat source pins and data contracts as requirements. Never fill unknown clinical settings, source semantics, checksums, benchmark results, or validation approvals with plausible guesses. Resolve source-level questions through pinned code and synthetic parity fixtures. Unknown medical/configuration facts become explicit UI states.

Do not implement algorithm shortcuts to make sample output look persuasive. Do not count proposed insulin as delivered insulin, interpret every Meal Bolus as a meal, apply one profile backwards through history, double-apply profile percentages, ignore rescue carbs, or replace the deterministic engine with an LLM. Do not promise exact attribution of cause from observational closed-loop data.

Keep all authorized engineering work moving even when a clinical-release gate remains outstanding. Finish the concrete code, tests, reproducible reference outputs and review package. Report gate status truthfully. Do not ask for permission to perform routine reversible implementation work, and do not change the user's live treatment setup.

## 22. Sources and provenance

Primary references checked 9 September 2026. Where links point to moving documentation, source-controlled implementations must use pinned revisions.

* [Nightscout API v3 tutorial](https://github.com/nightscout/cgm-remote-monitor/blob/master/lib/api3/doc/tutorial.md): v3 collection access, JWT authorization, modification history and invalidation. [v1 Swagger](https://github.com/nightscout/cgm-remote-monitor/blob/master/lib/server/swagger.yaml) and [v3 Swagger](https://github.com/nightscout/cgm-remote-monitor/blob/master/lib/api3/swagger.yaml) define protocol details to pin during W02.
* [Nightscout security documentation](https://nightscout.github.io/nightscout/security/) and [roles/admin tools](https://nightscout.github.io/nightscout/admin_tools/): credential handling and read-only access roles. Live API inspection established the deployment observations in section 2, not a full security audit.
* [Pinned AAPS source](https://github.com/nightscout/AndroidAPS/tree/1393357107a2b27ba153df31d64e745efd771ef2/plugins/aps/src/main/kotlin/app/aaps/plugins/aps/autotune): normative algorithm-port reference. [AAPS Autotune guide](https://androidaps.readthedocs.io/en/latest/AdvancedOptions/Autotune.html): supported outputs and limitations. [Dynamic ISF guide](https://androidaps.readthedocs.io/en/latest/DailyLifeWithAaps/DynamicISF.html): relationship to static profile sensitivity.
* [ADA 2026 glycemic goals guidance](https://doi.org/10.2337/dc26-s006): individualized goals, CGM metrics and hypoglycemia considerations. This source does not validate this application's proposed algorithm or engineering thresholds.
* [Qt for Python deployment](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html): native application deployment capabilities. Flatpak packaging here is an engineering choice for the user's Bazzite host.
* [llama.cpp build](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md) and [server documentation](https://github.com/ggml-org/llama.cpp/tree/master/tools/server): local runtime integration. [Qwen3-14B GGUF model card](https://huggingface.co/Qwen/Qwen3-14B-GGUF): official weight format/model choice, not medical validation.
* [Flatpak permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html): Wayland, DRI and filesystem access model.

All architecture, product thresholds, schema design, validation gates, and work sequencing are proposed engineering decisions. They must not be presented as clinical recommendations made by those sources.
