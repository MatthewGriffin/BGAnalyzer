# Project review and analysis-context corrections — 13 September 2026

Verification: baseline 200 tests passed; updated full suite 209 passed in 93.21 seconds. A subsequently added database-adapter regression passed with the four-test analysis-context suite. Selected Ruff checks and compileall passed. Existing Qt/pyqtgraph teardown warnings remain.

Reviewed the working tree and preserved/completed the unfinished IOB graph feature. Replaced guessed peak/DIA and bolus-only display-list calculation with source-linked AAPS uploaded IOB. Daily graph loading uses its own IOB sample range; negative/zero values are retained and invalid/conflicting/disappeared observations break the curve. One persistent overlay replaces per-refresh ViewBox creation.

Corrected analysis input handling: retain earlier insulin for explicit per-day DIA-plus-two-hour context; exclude disappeared glucose/treatments; preserve percentage-zero as 100% internal rate; omit missing-duration temps rather than invent 30 minutes; use actual local day ends for splitting and eligibility coverage. Added tests for DST, lookback boundaries, database normalization, IOB source semantics and graph lifecycle. No numerical release gate was relaxed.

See PROJECT_STATE.md for the current supported features and ordered remaining work. Full historical delivery and raw-to-result Kotlin parity remain incomplete.

# Incremental reconciliation repair — 12 September 2026

A later user report lost previously observed profile/configuration records after a fast poll. Root cause: ObjectId-filtered incremental fetches were passed to full-day disappearance reconciliation. Delta saves now only upsert/re-observe returned records; they do not mark absent IDs missing, certify full-window coverage, or extend full-backfill bounds. Forced imports ignore incremental ObjectId bounds. Full scans retain disappearance detection, and genuine re-observation clears prior missing flags. Do not bulk-clear disappearance records without re-reading the source.

Recovery: restart the running app to load the fixed polling logic, then run Sync report period (full scan of recent windows) to re-observe incorrectly flagged records and rebuild profile activations. Existing historical gaps and numerical-release blockers remain separate. Added both save-layer removal/recovery tests and an incremental integration fixture containing a record older than the ObjectId overlap.

# Report boundary and confirmation repair — 12 September 2026

Latest configuration selection now skips ordinary empty device-status configuration objects while retaining invalidation/disappearance filters, so later empty uploads do not hide explicit Dynamic ISF settings. Atlas SyncStats carries requested_end_ms; subsequent GUI report snapshots use that exact timestamp instead of advancing beyond the completed sync scope. Partial imports retain their missing windows; no clinical-data gaps are trimmed. Unchecked-window displays now include seconds.

Basal readiness exposes explicit unknown/yes/no meal-recording, autosens and Dynamic ISF confirmations for the selected period. Unknown does not add a confirmation. Values are not persisted and reset on range changes/new sync results; controls are disabled during computation. These are user-reported context, not proof of historical delivery. Earlier profile history, delivery verification and end-to-end parity remain unresolved.

# Permanent profile expiry repair — 12 September 2026

User report showed accepted switch records but zero evidence intervals. Pinned EPS.kt explicitly marks originalEnd unused. Read-only cache inspection found six zero-originalDuration uploads with originalEnd predating their event times. Resolve explicit originalDuration=0 as permanent; positive duration uses the event timestamp plus duration; requested duration=0 is likewise permanent. Legacy payloads without originalDuration retain the explicit-end fallback. Preserve pre-first-switch gaps and source provenance. Corrected the prior regression test that incorrectly expected permanent switches to have no interval; malformed switches still create gaps.

Read-only verification now finds six candidate intervals and 10.6% coverage over the current 14-day range, versus zero before. Remaining earlier history is still missing; sync rebuilds derived activations with the fixed resolver. Nested apsConfiguration.use_dynamic_sensitivity now feeds loop-mode evidence. Assumed delivery intervals no longer pass delivery verification. Verification: 68 affected tests passed and selected Ruff checks passed; Qt timer teardown warning remains. No dosage recommendations enabled.

# Startup and validation repair — 12 September 2026

Verification: application entry-point import, compileall and selected Ruff checks passed. Full suite: 205 passed in 93.08 seconds. One subsequently added empty-result rendering regression also passed in the 16-test focused run. Existing Qt/pyqtgraph teardown warnings remain.

Fixed an IndentationError in EligibilityChecker's leave-one-day-out sensitivity loop that prevented the application entry point from importing. Corrected nested basal/IC/ISF collection, removed the first-three-day cap, count only successful reruns, and fail the stability check on incomplete or failed reruns. Regression tests cover all-day omission and failure behavior.

The current suite exposed 16 failures. Repaired early-return delivery checks, removed automatic autosens/DynISF/meal confirmations, restored withheld status for ineligible analyses, and replaced the empty-result formatter's invented candidate/undefined variable with accurate text. Updated the synthetic TunedProfile fixture with its required explicit insulin fields. Removed a swallowed undefined-connection query that attempted to truncate the requested report interval.

Release audit validation now binds to the canonical full policy hash and every evidence-file hash, before candidates are attached to results. Existing audit files are preserved, but an approval label and arbitrary nonempty hash are insufficient. Component/core fixtures do not verify raw treatment/profile ingestion and preparation; removed the hard-coded end-to-end parity success. User clarified approval means technical validation, not a claim of clinical review.

Remaining technical blockers: source-bound raw-data-to-preparation/total-IOB comparison; complete historical delivery/context verification; reproducible end-to-end artifact tied to the current implementation; then evidence-bound release policy checks. No failed eligibility check is downgraded into actionable recommendations.

# Implementation checkpoint — 11 September 2026

## Verified switch semantics and per-record diagnostics (latest)

Real-data readiness showed switch uploads present but zero usable intervals, with no explanation of why. The pinned AAPS serializers were fetched and verified (EffectiveProfileSwitchExtension, ProfileSwitchExtension, BlockExtension, ProfileSealed vendored with hashes): switches carry the uncustomized base plus requested percentage/timeshift/duration, effective Notes carry already-effective content, customization is basal ×pct/100 with IC/ISF ×100/pct in exact operation order, and profile JSON carries DIA but never peak. Applied: requested switches now derive inferred activations (fixing the customization math, which scaled everything one way); mixed uploads must agree bit-exactly or gap; restatements coalesce; DIA/peak carry provenance with device-status peak overlay (mid-range changes still block); readiness censuses switch uploads by event type, covers the activation table, and now prints per-record verdicts naming the exact failing check. Latent bugs fixed: ended activations were invisible to history resolution, and "value"-keyed basal resolved to 0.0. Display trimmed: config evidence caps at 10 uploads, unchecked import windows show bounds.

Verification: full suite 189 passed; selected Ruff checks and compileall passed. Delivery verification, full AAPS parity and clinical policy review remain outstanding gates; no numerical recommendation was enabled.

## Switch evidence and insulin provenance follow-up (latest)

Real-data readiness showed 0% switch evidence, 0 analysis days, and "Baseline DIA/peak unresolved (DIA=5.0, peak=0)". Three fixes, all verified against newly pinned AAPS sources (EffectiveProfileSwitchExtension, ProfileSwitchExtension, BlockExtension, ProfileSealed at the pinned commit, vendored with hashes): requested Profile Switch uploads now derive inferred activations alongside effective Notes, with the base profile stored uncustomized and the requested percentage/time-shift applied downstream using the corrected customization math (basal ×pct/100, IC/ISF ×100/pct in exact operation order, targets shift-only — the old code scaled everything one way); mixed switch/note uploads at one timestamp must agree on effective content (compared bit-exactly after granularity normalization) or gap; identical restatements coalesce instead of slivering. DIA/peak now carry provenance: store-stated DIA stands, peak overlays from single-valued clean in-range device-status evidence (mid-range changes or absent evidence still block with named reasons). The readiness report also censuses profile stores and switch uploads by event type, covers the activation table (not just candidate intervals) for the history check, and states insulin provenance. Two latent bugs fixed en route: the activation loader hid every ended activation from history resolution, and schedule parsing resolved real "value"-keyed basal to 0.0.

Verification: full suite 183 passed; selected Ruff checks and compileall passed. If a deployment truly uploads no switches, the output now says exactly that and what would provide evidence. DIA/runtime activation between uploads, delivery verification, full AAPS parity and clinical policy review remain outstanding gates; no numerical recommendation was enabled.

## Eligibility inputs follow-up (latest)

Eligibility still ran on placeholders: freshness always passed, coverage unchecked, episode support guessed from day counts, low-glucose contradiction disabled, loop modes assumed off, insulin plugin never reported — and it only ever saw the first analysis day's glucose. All six now consume real inputs. Connection freshness compares newest cached glucose against the clock (15-minute bound, fail closed on skew). Eligible days are tuned days passing measured per-window CGM coverage (5-minute carry-forward matching the report model, windows clipped to the range so partial today is judged on elapsed time, not 24h). Episode support counts reference-categorized data (basal days, CRDatum carb episodes/days); ISF is never supported because the reference defines no correction episodes, stated as a limitation rather than a silent pass. Insulin increases are withheld on any valid BG below 54. Autosens/dynamic-ISF are tri-state (True/False/unknown) from raw upload keys with no silent defaults, overridable by explicit user confirmation labeled user-reported; unknown modes abstain with distinct codes, and the latest upload-stated insulin plugin feeds the configuration check. Orchestration keeps (day, prepped) pairs aligned and reports per-day categorized counts for all of this.

Verification: 10 new tests (freshness matrix, coverage/gap boundaries, range clipping, eligible-day gating, support thresholds, contradiction matrix, mode matrix, plugin, no-default device config, day-stat alignment); full suite 171 passed; selected Ruff checks and compileall passed. Remaining placeholders: leave-one-day-out sensitivity reruns and exclusion-day expansion; clinical policy review and full AAPS parity remain external/outstanding gates; no numerical recommendation was enabled.

## Activation derivation and day-loop hang fix (latest)

Two linked blockers resolved. First, the true basal-compute hang: skipping analysis days without a resolvable profile used `continue` before the loop advance, so any profile gap looped forever — on real data (empty activations) every run hung, and the old Cancel could not stop it. The advance now happens before the skip, with a termination regression test. Second, the empty activation table that made every day unresolvable: sync now rebuilds inferred activation evidence from effective-profile uploads after every backfill (full-history recompute, so corrections, expiries and disappearances converge with no orphans). Each observed interval becomes one `effective:<note>` profile version plus one certainty-"inferred", origin-"effective_note" activation; conflicts, malformed and disappeared uploads leave gaps, and the trailing interval stays open-ended. The timeline's already-customized path engages through the new `ProfileSource.EFFECTIVE_NOTE`, and schedule parsing accepts both "value" and "rate" keys instead of resolving real basal rates to 0.0.

Readiness and eligibility now consume the real timelines: the activation-history check passes on full inferred coverage (stating the inferred provenance), and eligibility fails closed with PROFILE_HISTORY_UNRESOLVED on any coverage gap and DELIVERY_HISTORY_UNRESOLVED on missing ranges or unknown/conflicted delivery intervals. The 3-day end-to-end run proves days resolve and autotune executes while numbers stay withheld at the remaining gates. DIA/peak provenance from profile JSON remains a stated limitation.

Verification: full suite 161 passed; selected Ruff checks and compileall passed. Clinical policy review and full AAPS parity remain external/outstanding gates; no numerical recommendation was enabled.

## Descriptive basal findings follow-up (latest)

Basal readiness completed imports yet showed no recommendations: numeric pump-setting output is intentionally withheld until delivery reconstruction, end-to-end AAPS parity and a reviewed clinical policy exist, but the tab also surfaced nothing else because the inherited pattern detectors were never wired in — and correctly so, since they do not implement the specified rules (UTC instead of local buckets, vacuous post-meal proportions, absolute-vs-net temp-basal confusion, whole-epoch coverage range). The tab now computes one faithful descriptive rule from the report snapshot: repeated low episodes per patterns-v1 (3 distinct local days, 15 covered minutes with 5-minute gap continuity, two-hour local bucket), listing contributing and conflicting days with episode times — no dose numbers, no causal claims. A single Check click now also loads a missing report first and auto-runs when it arrives, instead of silently doing nothing.

Verification: new tests cover grouping, the 15-minute boundary, gap splitting, local (DST-aware) bucketing, threshold/invalid/out-of-range exclusion, withheld-numbers wiring and the click-once UI chain. Full suite 149 passed; selected Ruff checks and compileall passed. Post-meal and loop-compensation descriptive rules remain future work; the legacy prototype detectors were left untouched.

## Incremental today-poll follow-up (latest)

"Reading devicestatus: MongoDB today" still stalled at range 1: the range never mattered, because the timestamp-conversion filter cannot use an index, so even a today-only poll scanned the entire collection (tens of thousands of devicestatus documents, hundreds of MB) every 60 seconds. The minute poll now carries an indexed `_id` lower bound: Nightscout assigns ObjectIds at document creation, so polls fetch only documents inserted since (last fully successful poll minus one hour overlap) and MongoDB uses the ever-present _id index plus filter. The overlap covers mid-scan commits and uploader clock skew; the cursor advances only after fully successful polls that ran faster than the overlap, and the first poll (or any manual/forced import) scans fully. Progress now shows record counts per chunk so a slow stage visibly moves. In-place server edits of old records are picked up by manual imports, not by bounded polls; this is stated in the UI-adjacent docs rather than silently assumed.

Verification: new tests cover the bound query shape for both filter styles, bound polls fetching only new ids with cursor advance, no cursor advance on chunk failure, and the worker marking only today polls incremental. Full suite 144 passed; selected Ruff checks and compileall passed. No numerical recommendation was enabled; all output remains withheld.

## Sync throughput and basal range follow-up (latest)

Basal readiness had no range control and stalled behind imports: every Atlas day window re-queried the remote collection, and the treatments/devicestatus filters convert stored timestamps server-side, which cannot use an index — so a 14-day import ran 42 full collection scans and the status bar never moved past "Reading … MongoDB today/history…". AtlasCoordinator.initial_backfill now fetches each requested span once in week-long chunks (14 days: 6 scans instead of 42) and persists the identical per-day windows, so coverage journaling, reconciliation, resume points, validation and cancellation semantics are unchanged. Verified with a fake range-honoring client: 10-day forced import uses 2 scans per collection, journals every day complete, and a repeat run skips completed days while rechecking only the recent span.

The Basal readiness tab now has a Range spinbox (1–90 days) sharing the Overview report range both ways. Pressing Check with a mismatched or missing report snapshot loads the matching range first and auto-starts the check when it arrives; pressing Check with no snapshot explains to load the report instead of silently doing nothing. Readiness output states the analyzed interval ("Analyzing: <dates> (N days)"). Cancelling while waiting for the report no longer leaves a stale auto-start pending.

Verification: full suite 140 passed; selected Ruff checks and compileall passed. No numerical recommendation was enabled; all output remains withheld.

## Basal hang follow-up (latest)

Basal readiness could run for ages with no working Cancel: the worker only checked interruption before/after the compute, never during it, so Cancel was a placebo. The pipeline now threads cooperative cancellation (new AutotuneCancelled in autotune/models.py) through build_basal_recommendations, snapshot building, day splitting, categorize/tune loops and eligibility staging, with per-day progress messages shown in the Basal readiness status line; cancelling ends the run promptly and the UI reports "Cancelled." instead of hanging on "Stopping…". The readiness output also records per-stage compute timings (snapshot/autotune/eligibility) to diagnose any residual slowness on real data.

Fixed two latent crashes found while profiling (both previously unreachable because sync never populates profile_activations): build_profile_timeline now parses string normalized_json and coerces TEXT percentage/time-shift values to numbers instead of crashing in resolve_profile/customization. Removed two performance hazards with identical results: tune_day converts each datum's local hour once instead of 24× per datum, and day splitting locates each day's slice with binary search instead of rescanning every list per day. Made the prototype-guard test honest by patching orchestration.run_full_autotune (the binding the readiness path actually uses; patching autotune.core was vacuous).

Verification: 90-day dense synthetic history (25,920 glucose, 30,780 treatments incl. SMB q5min) computes in ~2s; full suite 136 passed; selected Ruff checks and compileall passed. No numerical recommendation was enabled; all output remains withheld.

## Basal blocker follow-up (latest)

Fixed four honest-reporting blockers while keeping all numerical output withheld: eligibility no longer crashes on the stale/insufficient-day paths (added CONNECTION_STALE/INSUFFICIENT_DATA reason codes with STALE status mapping); readiness now emits explicit BLOCKED profile_activation_history, delivery_verification and aaps_end_to_end_parity checks instead of passing vacuously; orchestration no longer falls back to baseline on UnknownProfile (unresolvable days are skipped) and correctly converts ResolvedProfile schedules to 24 hourly rates with scalar IC/ISF; profile parsing expands half-hour boundaries and leaves missing DIA/peak as unknown (0) so eligibility flags them, with a pre-autotune guard that withholds when DIA/peak are unresolved. Added regression tests for each fix.

Verification: full suite 133 passed; selected Ruff undefined-name/syntax checks and compileall passed. Remaining blockers unchanged: sync never populates profile_activations (store uploads are not activation history), pump delivery is unconfirmed (endId cancellations/suspensions/offline gaps unresolved), meal preparation and full multi-day orchestration lack parity measurements, and no reviewed clinical policy exists. No numerical recommendation was enabled.

## Insulin action and temporary-basal reference components

Implemented isolated AGPL research translations and executable Kotlin comparisons for unchanged LocalInsulin.kt and the extracted AutotuneIob temporary-basal conversion. Insulin action: 1,125 cases / 2,250 values with zero differences. Temporary-basal conversion: 360 cases / 960 amounts and timestamps with zero differences. Result artifacts include source/translation hashes; reproduction and tested boundaries are documented in reference/README.md. Pinned AutotuneIob, its duration extension and T helper with hashes.

Corrected misleading legacy module descriptions: the existing triangular IOB approximation and delivery timeline are not verified AAPS ports. Runtime behavior was not changed and no numerical recommendation was enabled. Remaining work is actual historical delivery reconstruction, cancellations/suspensions, profile-boundary splitting, pre-window context, total IOB summation/rounding, meal preparation and complete orchestration. Passing these isolated calculations does not establish those inputs or clinical suitability.


## Historical insulin configuration observations

Readiness now reads current raw device-status configuration uploads with record IDs/revisions and invalidation/disappearance checks. It retains all observations in the report plus the nearest preceding nonempty configuration timestamp, including conflicting simultaneous records. Empty configurations are ordinary omitted uploads, not settings resets; malformed or disappeared nonempty records never trigger fallback to an older valid value.

Exact AAPS 3.4.2.1 observations can resolve rapid/ultra-rapid plugin peak constants from pinned source, or the explicit uploaded free-peak setting. Unknown/custom versions, unsupported plugins and missing/malformed free-peak settings remain unresolved. No brand inference, preference default, DIA substitution or historical interpolation is used. Latest dated evidence and historical issue counts appear in Basal readiness. All numerical output remains withheld; profile DIA/runtime limits, autosens, activation continuity and delivery/IOB remain unvalidated.

Pinned additional official serializer/interface/plugin sources and hashes in reference/aaps/manifest.json. Added unit and database integration tests for provenance, version gates, invalidation, missing peaks, conflicts and predecessor selection. The isolated AGPL source files remain outside the production package.


## Effective-profile coverage follow-up

Readiness now reports the union of candidate effective-profile intervals, exact missing periods and local timestamps with UTC offsets. This is observed evidence scope, not verified activation coverage. Invalid expiry values fail closed. Malformed effective uploads with missing profileJson remain timeline boundaries, preventing accidental continuation of the previous profile. Added tests for overlapping/clipped intervals, empty coverage, malformed profiles, invalid boundaries and displayed timezones. Insulin configuration and full delivery/IOB reconstruction remain outstanding; no numerical-release gate was relaxed.

## Basal readiness and reference comparison (latest)

Verification: 100 regression tests passed in 92.54 seconds. Selected Ruff undefined-name/syntax checks and compileall passed. Existing Qt/pyqtgraph teardown warnings persist; these checks do not establish clinical validity.

The Basal readiness tab replaces the unvalidated numerical recommendation display. It reads all cached treatments within a consistent read-only transaction, checks source revision and requested-window coverage, and reports profile, insulin configuration, delivery and validation blockers. It never invokes the inherited autotune prototype and always withholds numerical changes. Missing evidence does not mean the current basal settings are appropriate.

Effective-profile Note uploads are distinguished from requested Profile Switch records. Already-customized schedules are preserved without applying percentage/time shifts twice; zero basal values are preserved. Identical simultaneous effective uploads retain all source references; conflicting, malformed or disappeared uploads create gaps. These are candidate evidence intervals, not a validated activation timeline. Explicit insulin plugin/peak and delivery reconstruction remain unresolved.

The isolated AGPL reference workbench compares the basal section extracted from pinned AAPS Kotlin source against a research Python translation. Its recorded 72 synthetic cases / 1,728 hourly values have zero numerical differences. This validates only that component with preclassified deviations, not insulin/IOB reconstruction, meal classification, complete autotune orchestration or clinical suitability. See `reference/README.md` for reproduction, scope and licensing. The research module is not imported into the app.

Next: validate effective-profile history and insulin configuration, reconstruct confirmed delivery and pre-window IOB, then compare preparation and full multi-day orchestration against the pinned implementation. Numerical output remains unavailable until those checks and a reviewed clinical policy are complete. The local AI explains report evidence; it does not calculate dosing recommendations.


## Local AI integrated and installed (latest)

Replaced the inherited inference manager with pinned official llama.cpp b10900 Vulkan and Qwen3 8B Q4_K_M assets (full checksums/revisions in inference/catalog.py and docs/LOCAL_AI.md). Installer streams bounded downloads, checks SHA256, retains verified files and deletes failed partial downloads. Runtime/model are installed in the user's application cache. Real GPU enumeration identifies RX 7900 XTX separately from the integrated GPU.

Report explanation now has Install local AI, Explain with local AI, Cancel and CPU controls. LocalAIWorker runs installation/generation off the GUI thread. The app starts an authenticated 127.0.0.1 server in offline mode, disables proxy inheritance for inference, turns model thinking off and bounds output. Model output is strictly a selection of existing fact IDs; unrecognised/free-form claims are rejected and coverage/missing-time facts are always included. Displayed wording comes from deterministic report facts. Highlights carry evidence/model/runtime hashes and are included in exports. Refreshed reports clear stale highlights and explain why. No dosing policy was added by this integration.

Owned runtime groups terminate on cancellation/normal completion/app close. Linux launcher sets parent-death SIGTERM. Runtime unloads after every request, rather than remaining resident for ten minutes. Model hashes are verified before every startup. Downloaded archive is freshly extracted into a private temporary runtime directory; no unverified cache executable is launched. The runtime source pin and smaller model deliberately replace the plan's initial candidate choices for the tested first integration. Flatpak packaging remains unfinished.

Verification: real synthetic generation on RX 7900 XTX passed in 6.8 seconds including asset verification/startup/cleanup. A separate real LocalAIWorker/QThread run passed and confirmed owned process cleanup. Full suite passed 95 tests in 92.72 seconds; selected Ruff checks, compilation and wheel/sdist build passed. Existing Qt/pyqtgraph teardown warnings persist. CPU speed and clinical use are not validated. Current AI capability is report highlighting, not free-form medical advice. Other concurrent basal-related implementation appeared in the workspace; it was preserved, not medically validated as part of this work.


## Traceable report explanation (latest)

Added a Report explanation tab with deterministic arithmetic for coverage, missing time, glucose-band percentages and duration-weighted mean. It cites lowest/highest contributing readings by timestamp and source ID, explains duplicate/conflict handling and five-minute support limits, and distinguishes descriptive calculations from AI/dosing advice. Metrics and explanations now share metric_contributions, so provenance uses the same represented intervals as the results. Summary export schema v3 includes all contributing record IDs/revisions, glucose values, exact interval bounds/weights, data revision and SHA256 evidence fingerprint. Report calculations remain in the background worker. No clinical policy or model inference has been enabled.

Verification: 25 affected explanation/metrics/UI/treatment/MongoDB-worker tests passed, including exact reconstruction of totals/mean, clipped carry-in readings, conflicting timestamps, missing data and fingerprint revision changes. Selected Ruff checks/build were run. Qt teardown warnings remain. Next explanation work is replacing the unsafe inherited model verification/download/runtime lifecycle and then validating constrained model output against this factual evidence. The old inference manager remains disconnected.


## Linked treatment evidence timeline (latest)

Added a separate event plot beneath the daily glucose graph, sharing its time axis. Recorded carbs, boluses, SMBs and basal events occupy separate lanes; other event types remain visible in an Other lane. Combined carb/bolus records have two markers referencing the same event. Clicking shows plain-text evidence (recorded amounts, zero rates/percentages, timestamp/end, validity, delivery status, notes, source ID and revision) and a vertical time reference on both plots. No glucose value, causal effect or insulin delivery is inferred for a marker. Double-clicking a treatment-table row opens its local calendar day without changing the report period.

Daily report workers now include treatment records/counts and unresolved-presence IDs. Invalid and disappeared records are omitted from chart markers; the table labels presence uncertainty and details remain inspectable. The current newest-2,000-record display cap is explicitly disclosed. No database migration, remote operation or clinical algorithm changed.

Verification: 13 affected timeline/UI/MongoDB-worker tests passed after fixes, including combined markers, zero-valued evidence, literal notes, disappearance filtering, record navigation and multi-point click handling. Existing Qt/pyqtgraph teardown warnings remain. This implements evidence inspection only; local-model runtime and validated tuning remain outstanding.


## MongoDB-only transition (latest)

The application now uses AtlasCoordinator for every SyncWorker run, including today's automatic polling. Removed Nightscout URL/auth/secret controls, the hybrid checkbox and HTTP fallback. Missing MongoDB credentials now fail explicitly. Worker closes its MongoClient on success/failure/cancellation. Shared ingestion, checkpoint, correction and disappearance handling remains intact. Legacy Nightscout modules/config identity are retained internally for cache compatibility and transport regression tests; the production worker never constructs an HTTP client. Existing Atlas keyring identity is unchanged.

Found and fixed an intervening config regression: old api_mode/verify_ssl/timeout fields caused NightscoutConfig validation to reject the saved settings and silently load defaults. Legacy extras are now ignored, preserving saved database/cache identity. Restored the user-confirmed Cluster0 default. Atlas URI config compatibility field is excluded from serialization/repr.

Verification: initial full run 75 passed/1 failed (empty database default prevented a UI shutdown test from starting sync). After restoring the default and adding compatibility coverage, all 26 targeted MongoDB/Atlas/UI tests passed. Obsolete HTTP-worker integration expectations were replaced with MongoDB worker tests; transport-independent import/report tests remain. Selected Ruff checks and compilation passed. Live verification imported three 15-minute collection windows (entries, treatments, devicestatus) directly from MongoDB into a temporary database, then removed it; no health records or credentials printed and no live cache modified. Restart the app to load the new worker and controls. docs/ATLAS_SETUP.md and README describe current MongoDB-only behavior; older hybrid notes below are historical.


## Sync transport progress labels

Removed the generic “history window” progress label, which also appeared during today's Nightscout-only polling. HTTP pagination now explicitly announces Nightscout today/history at request entry, and Atlas cursor reads announce Atlas history. Profile-store reads also identify their transport. These messages describe the active operation, not a persistent record of which transport earlier imports used. All 17 Atlas/routing tests and selected Ruff checks pass, including an assertion for “Reading devicestatus: Nightscout today…”. Restart required for the running app to pick up the fix.


## Atlas history and daily graph implementation

User chose MongoDB Atlas for historical analysis/imports and Nightscout for today's values. Screenshot confirms both cluster and database are named Cluster0. Added PyMongo (locked 4.18.1), AtlasConfig, separate source/database-bound keyring URI storage, editable collection settings, TLS validation, and read-only cursor imports. HybridCoordinator routes history before local midnight to Atlas and today to Nightscout, preserving shared remote IDs, SQLite transactions, reconciliation and checkpoints. Scheduled polling now requests only today's local-midnight interval and never opens Atlas. Profile stores use Atlas for hybrid imports; Nightscout for live-only polling. No database/index writes are implemented.

Graph now has previous/next-day buttons, date picker and Today, showing one local calendar day with local timezone ticks and DST-correct boundaries. Multi-day report summaries and exports retain their independent selected range; cached historical days outside the report can still be viewed. Settings are scrollable. Setup and implementation limits are in docs/ATLAS_SETUP.md. The user must enter a dedicated read-only Atlas URI privately in the app; no live Atlas import or speed measurement has been performed.

Verification: full suite passed 87 tests; the final timestamp query revision passed a further 20 targeted Atlas/UI tests. An additional error-redaction/cursor-close regression also passed (17 Atlas tests total). Selected Ruff checks, compilation and wheel/sdist build passed. Existing Qt/pyqtgraph teardown warnings persist. Cursor tests use fakes, not a live MongoDB server. Date conversion for treatment/device timestamps handles ISO offset spellings but may scan rather than use a plain string-date index. Numerical recommendation/model restrictions below remain unchanged.


## Report-period sync correction

After HTTP fixes, a complete import still covered only 14.3% of the 14-day report. Overview's button was hard-coded to sync two days. It now reads the selected report_days value on click and is labelled “Sync report period”. Connection history settings and automatic polling retain their existing behavior. All three UI tests and selected Ruff checks pass; the new regression clicks the button at 14 and 30 days and verifies both requested scopes. Restart the running app to load this change, select 14 days, and click Sync report period to fill historical gaps.


## Follow-up: query-array limit confirmed

The user's 14-day import failed on entries window 1788998400000–1789055139777. Live comparison found the unexcluded request returned HTTP 200 with 372 records; excluding 1 or 20 IDs returned 200, while 21 or 32 IDs returned HTTP 500. Thus the earlier 32-ID limit was insufficient, and the previous attribution of these 500s to general server availability was not established. Sync now uses MAX_EXCLUDED_IDS = 20 throughout subdivision and same-timestamp pagination. The large-page regression asserts this stricter bound. Retry and completeness validation remain in place. The exact previously failing live window completed with 372 unique records after the change; no user cache was modified. Targeted verification passed: 26 client/journal tests, 2 worker pagination tests and selected Ruff checks. A full live 14-day import has not been rerun.

## Latest sync repair (read first)

Reproduced HTTP 502 from a roughly 27 KB URL containing 471 excluded record IDs. Pagination now subdivides time windows before exclusion lists exceed 32 IDs, with bounded same-timestamp pagination and explicit incomplete-boundary errors. The client rejects URLs over 4096 bytes before sending. Retries are bounded and cancellable; persistent server failures stop the import pass and display the HTTP status.

Verification: 69 tests passed, selected Ruff checks and compilation passed, and wheel/source distribution built. Tests cover oversized queries, large-page subdivision, cancellable retries and persistent server errors. GUI tests use temporary XDG paths and mocked network requests. Qt still prints a timer warning at test teardown.

Live verification remains incomplete: status recovered to HTTP 200, but a subsequent isolated one-hour entries request returned HTTP 500. Earlier requests also returned 503/timeouts. Server availability remains a separate issue. Diagnostics did not write into the user's database. The user reported an application crash; no crash markers were found in available recent application logs, so its cause is unresolved.

Since the older checkpoint below, persistent sync journals/resumption, disappearance tracking, source-revision invalidation, asynchronous report snapshots and worker lifecycle regression coverage have been implemented. The older next-work list is historical; inspect these implementations before repeating that work. Numerical recommendation and local-model restrictions below still apply.


## Start here after interruption

Read this file, then inspect the repository. Do not recreate the plan or scaffold. Run the regression suite before changing behavior. All original generated modules were preserved unless replaced with working implementations. Many unused prototype modules remain unverified; file presence is not feature completion.

## Verified working path

`__main__ → AppController → MainWindow → SyncWorker → NightscoutClient / SyncCoordinator → Repository / SQLite → calculate_tir_metrics / cached charts`.

The main window was missing at takeover. It now launches, has Overview, Treatment records, Data quality and Connection tabs, runs network imports in a QThread, cancels between requests, and waits for its worker before closing. The application uses QLockFile for exclusive process access. It does not yet focus an existing window on a second launch.

Fixed broken package `__all__` initialization, migration datetime call, zero dose/rate persistence, raw revision idempotence, nested transaction rollback, system-path configuration, secret serialization, dated UTC request filters, real Nightscout `store` object parsing, invalidation handling, SMB classification, compressed-response decoding, and glucose duration weighting/day-percentile aggregation.

`uv.lock` now records resolved dependencies. All application modules import. The offscreen desktop starts using a fresh temporary database.

The live two-day v1 check completed with 876 glucose records, 85 treatment records, 588 device-status records and 95 profile-store entries, and zero incomplete windows. These counts reflect that inspection, not a promised server retention window. Temporary clinical data was removed. No live credential was used.

## Explicit restrictions

* No writes to Nightscout, AAPS, or the pump.
* `check_eligibility` returns `validation_unavailable`; `generate_candidates` returns no candidates. Do not restore the earlier always-true checks.
* The existing autotune files contain heuristic prototype code, not a verified AAPS port. No parity harness or approved numeric policy exists.
* Existing inference manager is not connected to the UI and is not verified: command flags, download verification and lifecycle need replacement before use.
* No general diabetes chat or dosing advice UI is exposed.

## Next work in order

1. Expand sync integration tests: complete GUI worker lifecycle with a mock server, failure/cancellation, configurable server caps and paging ties, authentication, late corrections and malformed records. Existing tests cover basic transaction rollback, page subdivision, idempotence, profile stores, SMB and invalidation.
2. Finish persistent backfill coverage/checkpoints: successful windows are stored but a restart currently repeats requested windows rather than resuming only missing windows. Handle lower-than-requested server caps, v1 disappearance/reconciliation and source revision invalidation of saved analyses. Profile history currently requests a bounded list; it does not establish complete historic activation.
3. Replace unused v1/v3 model prototypes with verified adapters or retire them. The working sync currently reads raw dictionaries directly. Several legacy `_id` Pydantic fields and old probe paths are not used by the working GUI.
4. Audit timestamp precedence, percentage-temp semantics, pump delivery confirmation, duplicates, profile activation/customization and raw-to-derived links against the pinned AAPS source. Treatment delivery currently remains `unknown`; do not label its sum as delivered total.
5. Move larger cached report queries/statistics off the main UI thread, add richer treatment/chart linkage, coverage/quality detail, annotations and evidence reports. The treatment table currently shows the newest 2,000 records in the selected period; the full cache is retained. Gaps over ten minutes break chart lines. Chart axis is explicitly UTC.
6. Implement the pinned AAPS reference harness and numerical port in the plan. The inherited math must not be used as a substitute for that work.
7. Replace and integrate the model manager: immutable catalog hashes, real packaged llama.cpp, verified GPU selection, authenticated loopback lifecycle, constrained evidence explanations and deterministic fallback.
8. Complete Flatpak packaging and actual Wayland host acceptance; no Flatpak artifact has been built. Complete validation gates honestly before exposing numerical treatment suggestions.

## Test commands

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q
.venv/bin/ruff check src tests --select F821,F822,F823,E9
.venv/bin/python -m compileall -q src
```

The codebase still has inherited broad-lint/type-quality debt. Passing the selected undefined-name/syntax checks is not a claim that full strict mypy or all configured Ruff rules pass.

## Latest verification result

30 regression tests passed. Undefined-name/syntax checks passed. Both the Python wheel and source distribution built successfully. Offscreen Qt emitted a timer warning at interpreter teardown; startup and UI assertions passed, but a real Wayland acceptance run remains required. Flatpak packaging and a complete strict-type/lint pass have not been performed.
