# Project state — 13 September 2026

## Working application

BGAnalyzer is a native PySide6 desktop application with MongoDB Atlas as its only live remote data source. It retains an SQLite cache, import-scope checkpoints, raw revisions and disappearance records. Daily glucose/treatment navigation is separate from the multi-day analysis report. Fast incremental polls upsert returned records; only full scans establish disappearance and complete imported scope.

The local model runs through an app-managed llama.cpp process. Its current supported output highlights existing report evidence; it does not generate insulin settings. Existing model/runtime setup and earlier hardware verification are documented in LOCAL_AI.md.

The IOB graph displays AAPS-uploaded observations at their own sample timestamps. It preserves negative/zero values, source record IDs and revision hashes, omits malformed timestamps, marks invalid/disappeared/conflicting values as unknown, and breaks lines across long gaps. It uses the selected graph day and a persistent right-axis overlay. It is not the app's reconstructed total IOB. No peak/DIA defaults or truncated treatment list are used for this graph.

## Basal analysis progress

Permanent requested/effective profiles now use duration semantics correctly. Derived history remains inferred evidence, with gaps before the first usable upload. User meal/mode confirmations are explicit and period-specific. Policy audit checks bind to exact policy and evidence hashes, and failed eligibility keeps results withheld.

Component reference comparisons exist for basal updates, individual insulin-action contributions, temporary-basal contribution conversion and prepared-input core fixtures. These do not establish raw-data-to-result parity.

The analysis adapter now retains cached insulin before the requested range and supplies each day's explicit DIA-plus-two-hour context. It excludes invalid/disappeared glucose and treatments. Percentage temp basals use internal total percent (wire offset + 100), including wire zero as 100%. Missing durations are not replaced with 30 minutes. Day boundaries and eligibility statistics use actual local calendar ends, including 23/25-hour days.

## Remaining work, in dependency order

1. Resolve raw delivery semantics through the production pipeline. The legacy delivery timeline still uses inconsistent raw/normalized field names, guesses cancellation links, assumes scheduled delivery in gaps and has unverified confirmation labels. Validate pump cancellation/suspension semantics, historical profile changes, percentage conversion at schedule boundaries and source provenance. Do not promote assumptions to confirmed delivery.
2. Verify historical insulin configuration throughout each analysis interval and its lookback. A known plugin peak at an upload does not establish continuous DIA/peak/profile history. Report missing context explicitly.
3. Run an executable pinned-Kotlin comparison from synthetic raw treatment/profile records through splitting, net-basal contributions, total IOB/activity, meal/UAM preparation and chronological tuning. Include cancellations, revisions, invalidation, conflicts, profile changes, negative net basal, clock changes, missing pre-window context and malformed inputs. Bind results to exact production source hashes; prepared-input core fixtures cannot substitute for this.
4. Validate the release policy and all prerequisite checks together: context, coverage, contradictions, sensitivity reruns, quantization, bounds, source revision, lookback scope and audit integrity. Technical approval is not a claim of clinical certification. Do not manufacture an approval file or relax a failed check merely to produce settings.
5. Finish packaging and host acceptance. The development app works; Flatpak distribution and a complete strict typing/lint pass are not established. Existing Qt teardown warnings remain under investigation.

## Verification commands

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q
.venv/bin/ruff check src tests --select F821,F822,F823,E9
.venv/bin/python -m compileall -q src
.venv/bin/python -m bganalyzer
```

The graph and adapter improvements do not enable numerical recommendations. Historical uploads cannot be recreated by changing a validation flag.

## Hourly explanation UI

The window now has five tabs, with Data quality fourth. The empty Report explanation tab and obsolete blanket unavailability notice are removed. Basal candidates remain individual hourly rows with five columns. Selection opens a deterministic plain-English explanation; a checkbox reveals retained calculation metadata and prepared readings. Explanations count the direction of daily summed deviations, distinguish mixed or missing evidence, and do not equate deviation with high/low glucose. They preserve eligibility and rejection status. Full intermediate calculation attribution and source-linked drill-down remain incomplete.

Additional product work from the specification includes connecting recommendation lifecycle and manual-change tracking to the UI, before/after outcome reports, and restoring usable local-AI controls. Existing backend modules do not establish completed user workflows. The original specification's Nightscout transport and tab layout are superseded by the user's MongoDB-only and simplified-tab requests.
