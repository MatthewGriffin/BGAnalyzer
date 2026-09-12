# AAPS reference workbench — not a released recommendation engine

This directory is isolated research tooling and is not imported by BGAnalyzer or included in its wheel. Upstream sources and the research translation are under **AGPL-3.0**; retain `aaps/LICENSE.txt` and the recorded upstream provenance. Any future integration/distribution of translated code requires resolving the application's license accordingly. The application metadata's existing MIT designation does not relicense this workbench.

`aaps/manifest.json` pins AndroidAPS 3.4.2.1 commit `1393357107a2b27ba153df31d64e745efd771ef2` and hashes the upstream files. `run_basal_parity.py` verifies those hashes, extracts the unchanged basal section from AutotuneCore.kt, and compiles it with the unmodified upstream Round.kt. The wrapper supplies explicit hourly profiles, ISF, bounds, timestamped preclassified deviations and timezone. It does not invoke the Android application or the full Autotune prep pipeline.

## Reproduce

Install an isolated Java 17 runtime and download the official Kotlin compiler 2.0.21. The run verified here used the PyPI package `jdk4py==17.0.9.2` in `/tmp/bg-aaps-ref-env`, and the official compiler archive from `https://github.com/JetBrains/kotlin/releases/download/v2.0.21/kotlin-compiler-2.0.21.zip`, extracted to `/tmp/bg-kotlin`.

```bash
.venv/bin/python reference/run_basal_parity.py \
  --java /tmp/bg-aaps-ref-env/lib/python3.12/site-packages/jdk4py/java-runtime/bin/java \
  --kotlin-lib /tmp/bg-kotlin/kotlinc/lib
```

The script compares the executable Kotlin output to `research/basal_component.py`, writes `basal-parity-result.json`, and fails on a mismatch. It checks 72 deterministic synthetic cases (1,728 hourly rates), including positive/negative/no deviations, differing prior/pump profiles, bounds, midnight wraparound, UTC/Europe-London and DST dates. Latest comparison: zero numerical differences. Upstream's pre-smoothing bounds and sequential smoothing order are preserved; the harness does not claim those choices constitute a suitable clinical policy. Zero denominators and missing dates are explicitly unsupported by the research translation.

## Required before any numerical release

This passing component test does **not** validate historical effective-profile reconstruction, insulin settings, delivery reconstruction, pre-window IOB, meal/UAM categorization, filtering, complete multi-day orchestration or clinical policy. Those gates remain blocked in the app. Profile-store uploads cannot stand in for effective activations; the app now distinguishes requested Profile Switch records from already-customized effective Note uploads, preserving zero rates and avoiding duplicate percentage application. Candidate effective intervals remain diagnostic evidence until the whole pipeline is validated.

## Insulin configuration evidence protocol

The production evidence reader follows the pinned [RunningConfigurationImpl serializer](https://github.com/nightscout/AndroidAPS/blob/1393357107a2b27ba153df31d64e745efd771ef2/plugins/configuration/src/main/kotlin/app/aaps/plugins/configuration/configBuilder/RunningConfigurationImpl.kt): running configuration is periodically omitted, and insulin plugin ID and plugin-specific settings are separate fields. The manifest also pins the insulin interface, rapid/ultra-rapid/free-peak plugins and preference key declarations. Fixed plugin peaks are labelled as source constants, not uploaded settings. Free-peak values must be explicitly uploaded; the preference default is never used. Version interpretation is limited to the pinned release. Observations are not proof of configuration activation between uploads, and DIA/runtime limits require separate resolution.

## Insulin action and temporary-basal conversion

`run_insulin_parity.py` compiles the unchanged pinned LocalInsulin.kt with minimal BS/Iob data containers. It compares 1,125 explicit synthetic cases (2,250 IOB/activity values) against `research/insulin_component.py`: zero numerical differences. Cases include signed net-basal amounts, zero amounts, millisecond elapsed times, peak points and the duration boundary. The reference's minimum-DIA clamp is preserved for explicitly supplied DIA; it must not be mistaken for reconstruction of a user's historical runtime settings. Future treatments and singular/invalid parameters are rejected by the research API.

`run_temp_basal_parity.py` extracts the unchanged `AutotuneIob.convertToBoluses(TB,...)` section and the exact duration extension, using unmodified Round.kt and T.kt. It compares 360 cases (960 signed contributions) against `research/temp_basal_component.py`: zero amount or timestamp differences. Inputs are already-resolved segments with explicit historical and comparison basal rates. Tests cover absolute/percentage rates, zero basal, negative net basal, half-step rounding and durations around whole-minute/five-minute boundaries. Internal percentage inputs use total percent (100 = neutral), whereas Nightscout's serialized percent field is an offset; the raw adapter must convert that separately.

Run either harness using the same Java/Kotlin paths as the basal harness above:

```bash
.venv/bin/python reference/run_insulin_parity.py --java /tmp/bg-aaps-ref-env/lib/python3.12/site-packages/jdk4py/java-runtime/bin/java --kotlin-lib /tmp/bg-kotlin/kotlinc/lib
.venv/bin/python reference/run_temp_basal_parity.py --java /tmp/bg-aaps-ref-env/lib/python3.12/site-packages/jdk4py/java-runtime/bin/java --kotlin-lib /tmp/bg-kotlin/kotlinc/lib
```

These comparisons do not validate delivered-insulin reconstruction or total IOB. Next work must resolve raw cancellation/end IDs and suspend/resume semantics; establish historical profile boundaries; split actual/percentage basal segments; retain source IDs on generated contributions; and compare total IOB including pre-window contributions and rounding. The pinned initializer fetches a DIA-plus-two-hour context range, while its IOB summation excludes future contributions and those older than the model duration. Import-scope and historical-setting checks must also cover the chosen lookback. Missing pump reports cannot be relabelled confirmed delivery. Extended boluses, emulated temp basals and neutral-fill semantics require their own reference tests.

The inherited production `autotune/insulin.py` triangular approximation and `timeline/insulin.py` reconstruction remain unvalidated and are explicitly labelled accordingly. Neither is a substitute for these reference components. No research numerical module is imported into the application.

## Profile-switch upload semantics (verified, no harness)

The manifest additionally pins `EffectiveProfileSwitchExtension.kt`, `ProfileSwitchExtension.kt`, `BlockExtension.kt` and `ProfileSealed.kt` (hashes verified against the pinned commit at fetch time). Read directly from those sources, without re-deriving from documentation:

* Effective uploads are `eventType "Note"` records carrying the already-effective pure profile (`profileJson` with `units`, `dia`, `timezone`, `sens`/`carbratio`/`basal`/`target_low`/`target_high` schedules of `{time, timeAsSeconds, value}`) plus `originalProfileName`, `originalCustomizedName`, `originalTimeshift`, `originalPercentage`, `originalDuration`, `originalEnd`. AAPS itself discriminates them by presence of `originalProfileName`.
* Requested switches are `eventType "Profile Switch"` records carrying the UNCUSTOMIZED base profile (customization is zeroed before serializing) plus top-level `timeshift` (ms), `percentage` (int), `duration` (minutes) and `originalDuration` (ms, preferred). Effective content is base customized by percentage/timeshift for the requested duration. Switches entered through Nightscout carry no `profileJson` and are unresolvable locally.
* Customization math, applied in this order: basal `amount * percentage / 100.0`, IC/ISF `amount * 100.0 / percentage`, targets shift in time without scaling; schedule lookup uses wall-clock time minus whole-hour shift with midnight wraparound. The production timeline previously scaled every schedule by `percentage / 100.0`; it now follows the pinned order bit-for-bit (verified by unit tests, not by JVM execution).
* `profileJson` carries DIA but never peak; peak resolves only from dated device-status insulin configuration.
