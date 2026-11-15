"""Basal analysis and recommendations.

Runs the pinned AAPS Autotune port and generates candidates when eligibility
and policy checks pass. Numerical output is withheld until validation gates pass.
"""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo
from collections import Counter
import time

from bganalyzer.autotune.models import AutotuneCancelled, throw_if_cancelled

from bganalyzer.db.connection import get_connection
from bganalyzer.db.sync_journal import SyncJournal
from bganalyzer.timeline.profile_evidence import (
    diagnose_switch_records,
    observed_profile_intervals,
    profile_evidence_coverage,
)
from bganalyzer.timeline.insulin_evidence import insulin_configuration_evidence
from bganalyzer.timeline.insulin import DeliveryOrigin
from bganalyzer.autotune.orchestration import (
    build_analysis_snapshot,
    run_full_autotune,
)
from bganalyzer.recommendations.eligibility import (
    EligibilityChecker,
    EligibilityStatus,
    ReasonCode,
)
from bganalyzer.recommendations.policy import (
    get_policy,
    NumericalReleasePolicy,
)

REFERENCE_COMMIT = "1393357107a2b27ba153df31d64e745efd771ef2"

# Descriptive grouping rule for repeated low episodes (plan patterns-v1
# subset). Three distinct local days with valid readings below the low band
# for at least 15 covered minutes in the same two-hour local clock bucket; a
# gap over five minutes breaks continuity. This is a product grouping
# heuristic, not a treatment threshold, and never produces dose numbers.
PATTERNS_VERSION = "patterns-v1"
LOW_BAND_MGDL = 70.0
LOW_MIN_DAYS = 3
LOW_MIN_COVERED_MINUTES = 15.0
LOW_MAX_GAP_MINUTES = 5.0
LOW_BUCKET_HOURS = 2


def describe_low_patterns(readings, start_ms, end_ms, timezone, threshold_mgdl=LOW_BAND_MGDL):
    """Group repeated low-glucose episodes descriptively.

    readings are GlucoseReading-like objects (event_ms, sgv_mgdl, valid); only
    valid in-range readings are used. Returns a list of finding dicts with
    local bucket, contributing/conflicting local days and episode details.
    Pure function: no database, network, or recommendation output.
    """
    zone = ZoneInfo(timezone)
    below = sorted(
        (
            (r.event_ms, float(r.sgv_mgdl))
            for r in readings
            if getattr(r, "valid", True)
            and r.event_ms is not None
            and start_ms <= r.event_ms < end_ms
            and r.sgv_mgdl is not None
            and float(r.sgv_mgdl) < threshold_mgdl
        ),
        key=lambda item: item[0],
    )
    episodes = []
    run = []
    for stamp, value in below:
        if run and stamp - run[-1][0] > LOW_MAX_GAP_MINUTES * 60000:
            episodes.extend(_close_low_run(run))
            run = []
        run.append((stamp, value))
    episodes.extend(_close_low_run(run))

    # Days with any valid in-range reading in each local bucket: the pool of
    # days that could have contributed an episode but did not (conflicting).
    bucket_coverage: dict[int, set] = {}
    for r in readings:
        if not getattr(r, "valid", True) or r.event_ms is None:
            continue
        if not start_ms <= r.event_ms < end_ms:
            continue
        local = datetime.fromtimestamp(r.event_ms / 1000, zone)
        bucket = (local.hour // LOW_BUCKET_HOURS) * LOW_BUCKET_HOURS
        bucket_coverage.setdefault(bucket, set()).add(local.date().isoformat())

    by_bucket: dict[int, list] = {}
    for episode in episodes:
        local = datetime.fromtimestamp(episode["start_ms"] / 1000, zone)
        bucket = (local.hour // LOW_BUCKET_HOURS) * LOW_BUCKET_HOURS
        by_bucket.setdefault(bucket, []).append((local.date().isoformat(), episode))

    findings = []
    for bucket in sorted(by_bucket):
        dated = by_bucket[bucket]
        days = sorted({day for day, _ in dated})
        if len(days) < LOW_MIN_DAYS:
            continue
        findings.append(
            {
                "rule": "repeated_low_episodes",
                "rule_version": PATTERNS_VERSION,
                "bucket_start": f"{bucket:02d}:00",
                "bucket_end": f"{(bucket + LOW_BUCKET_HOURS) % 24:02d}:00",
                "low_threshold_mgdl": threshold_mgdl,
                "contributing_days": days,
                "episode_count": len(dated),
                "episodes": [
                    {
                        "date": day,
                        "start": datetime.fromtimestamp(ep["start_ms"] / 1000, zone).strftime(
                            "%d %b %H:%M"
                        ),
                        "covered_minutes": round(ep["covered_minutes"], 1),
                        "min_mgdl": round(ep["min_mgdl"], 1),
                    }
                    for day, ep in sorted(dated, key=lambda item: item[1]["start_ms"])
                ],
                "days_with_readings_no_episode": sorted(bucket_coverage.get(bucket, set()) - set(days)),
            }
        )
    return findings


def _close_low_run(run):
    """Turn one gap-unbroken below-threshold run into episodes (0 or 1)."""
    if not run:
        return []
    covered = (run[-1][0] - run[0][0]) / 60000 + LOW_MAX_GAP_MINUTES
    if covered < LOW_MIN_COVERED_MINUTES:
        return []
    return [
        {
            "start_ms": run[0][0],
            "covered_minutes": covered,
            "min_mgdl": min(value for _, value in run),
        }
    ]


def build_basal_recommendations(snapshot, config, timezone, settings=None, cancelled=None, progress=None):
    """Build basal recommendations from autotune analysis.

    Runs the full AAPS Autotune pipeline and generates candidates
    when eligibility and policy checks pass.

    cancelled is an optional zero-arg callable; AutotuneCancelled is raised
    promptly when it returns True so the UI Cancel button actually stops the
    computation. progress, if given, receives short status strings.
    """
    result = {
        "status": "withheld",
        "recommendations": [],
        "descriptive_findings": [],
        "switch_diagnosis": [],
        "sync_quality": {},
        "reference_commit": REFERENCE_COMMIT,
        "message": "",
        "checks": [],
        "counts": {},
        "timings": {},
    }
    checks = result["checks"]

    def check(code, passed, detail):
        for item in checks:
            if item["code"] == code:
                item["passed"] = passed
                item["detail"] = detail
                return
        checks[:] = [item for item in checks if item["code"] != code]
        checks.append({"code": code, "passed": passed, "detail": detail})

    def announce(text):
        if progress is not None:
            progress(text)

    throw_if_cancelled(cancelled)

    if snapshot is None or snapshot.source_id is None:
        check("source", False, "No imported source selected.")
        result["message"] = "No source selected for analysis."
        return result

    source, start, end = snapshot.source_id, snapshot.start_ms, snapshot.end_ms
    # Preserve the requested interval: missing CGM at its end is evidence, not a reason to hide the gap.
    announce("Grouping repeated low-glucose observations…")
    result["descriptive_findings"] = describe_low_patterns(
        getattr(snapshot, "readings", []) or [], start, end, timezone
    )
    conn = get_connection(config, read_only=True)
    conn.execute("BEGIN")

    try:
        revision = conn.execute("SELECT COALESCE(MAX(revision),0) FROM data_revisions").fetchone()[0]
        result.update(source_id=source, start_ms=start, end_ms=end, data_revision=revision, timezone=timezone)

        check(
            "snapshot_revision",
            revision == snapshot.data_revision,
            "The input audit and displayed report must use the same cache revision.",
        )

        check("delivery_verification", False, "Delivery reconstruction has not yet completed for this report.")

        # Load full treatment cache
        rows = conn.execute(
            "SELECT remote_id,revision_hash,event_ms,kind,delivery_status,valid FROM treatments WHERE source_id=? AND event_ms>=? AND event_ms<? ORDER BY event_ms,remote_id",
            (source, start, end),
        ).fetchall()

        missing = {
            r[0]
            for r in conn.execute(
                "SELECT remote_id FROM sync_disappearances WHERE source_id=? AND collection='treatments' AND resolved_ms IS NULL",
                (source,),
            )
        }
        usable = [r for r in rows if r["valid"] and r["remote_id"] not in missing]
        kinds = Counter(r["kind"] for r in usable)
        unconfirmed = sum(
            r["delivery_status"] != "delivered"
            for r in usable
            if r["kind"] in ("bolus", "smb", "temp_basal")
        )
        result["counts"].update(
            all_treatments=len(rows),
            usable_treatments=len(usable),
            invalid_or_missing=len(rows) - len(usable),
            unconfirmed_insulin_records=unconfirmed,
            by_kind=dict(kinds),
        )
        check("full_treatment_cache", True, f"Read all {len(rows)} cached treatment records in the interval.")

        # Sync quality checks
        quality = SyncJournal(config).summary(source, start, end, connection=conn)
        result["sync_quality"] = {
            collection: {
                "missing_windows": [
                    [lo, hi] for lo, hi in quality[collection]["missing_windows"]
                ]
            }
            for collection in ("entries", "treatments", "devicestatus")
        }
        for collection in ("entries", "treatments", "devicestatus"):
            item = quality[collection]
            check(
                "import_scope_" + collection,
                not item["missing_windows"],
                f"{len(item['missing_windows'])} unchecked {collection} intervals — trigger sync for range.",
            )

        # Profile evidence
        profiles = conn.execute(
            "SELECT remote_id,revision_hash,effective_from_ms,profile_name,timezone,units_original FROM profile_versions WHERE source_id=? AND effective_from_ms<? ORDER BY effective_from_ms",
            (source, end),
        ).fetchall()
        result["profile_store_evidence"] = [dict(r) for r in profiles]

        activations = conn.execute(
            "SELECT a.start_ms,a.end_ms,a.certainty,a.origin,a.evidence_json,p.remote_id FROM profile_activations a JOIN profile_versions p ON p.id=a.profile_version_id WHERE p.source_id=? AND a.start_ms<? AND (a.end_ms IS NULL OR a.end_ms>?)",
            (source, end, start),
        ).fetchall()
        result["counts"]["profile_store_versions"] = len(profiles)
        result["counts"]["activation_records"] = len(activations)
        result["counts"]["inferred_activation_records"] = sum(
            1 for a in activations if a["origin"] in ("effective_note", "profile_switch")
        )

        raw_profiles = conn.execute(
            "SELECT remote_id,revision_hash,event_ms,payload_json,is_valid FROM raw_records WHERE source_id=? AND collection='treatments' AND is_current=1 AND event_ms<? AND (json_extract(payload_json,'$.profileJson') IS NOT NULL OR json_extract(payload_json,'$.originalCustomizedName') IS NOT NULL OR json_extract(payload_json,'$.eventType') = 'Profile Switch')",
            (source, end),
        ).fetchall()
        census = conn.execute(
            "SELECT json_extract(payload_json,'$.eventType') AS event_type, COUNT(*) FROM raw_records WHERE source_id=? AND collection='treatments' AND is_current=1 AND event_ms>=? AND event_ms<? AND (json_extract(payload_json,'$.profileJson') IS NOT NULL OR json_extract(payload_json,'$.originalCustomizedName') IS NOT NULL OR json_extract(payload_json,'$.eventType') = 'Profile Switch') GROUP BY event_type",
            (source, start, end),
        ).fetchall()
        result["counts"]["profile_bearing_by_event"] = {
            (row[0] or "unknown"): row[1] for row in census
        }
        observed = observed_profile_intervals(
            [
                dict(row, presence_unknown=row["remote_id"] in missing or not row["is_valid"])
                for row in raw_profiles
            ],
            start,
            end,
        )
        result["switch_diagnosis"] = diagnose_switch_records(
            [
                dict(row, presence_unknown=row["remote_id"] in missing or not row["is_valid"])
                for row in raw_profiles
            ],
            start,
            end,
        )
        coverage = profile_evidence_coverage(observed, start, end)
        result["profile_evidence_coverage"] = coverage
        result["observed_profile_intervals"] = observed
        result["counts"]["observed_effective_profile_intervals"] = len(observed)
        result["counts"]["observed_switch_intervals"] = sum(
            1 for interval in observed if interval.get("kind") == "ps"
        )

        check(
            "effective_profile_scope",
            not coverage["gaps"],
            f"{coverage['coverage_percent']:.1f}% of the report interval has candidate switch evidence; {len(coverage['gaps'])} gaps.",
        )
        check(
            "effective_profile_evidence",
            bool(observed),
            f"{len(observed)} candidate intervals from {result['counts']['observed_switch_intervals']} requested switch(es) and "
            f"{len(observed) - result['counts']['observed_switch_intervals']} effective Note(s).",
        )
        # Activation-table coverage is what tuning consumes: derived rows of
        # any origin must tile the interval without gaps.
        activation_coverage = profile_evidence_coverage(
            [
                {"start_ms": a["start_ms"], "end_ms": a["end_ms"] if a["end_ms"] is not None else end}
                for a in activations
            ],
            start,
            end,
        )
        result["activation_coverage"] = activation_coverage
        inferred = [a for a in activations if a["origin"] in ("effective_note", "profile_switch")]
        confirmed = [a for a in activations if a["origin"] not in ("effective_note", "profile_switch", "unknown")]
        check(
            "profile_activation_history",
            not activation_coverage["gaps"],
            f"{len(inferred)} inferred activation(s) derived from switch uploads "
            f"({activation_coverage['coverage_percent']:.1f}% of the interval) plus "
            f"{len(confirmed)} confirmed record(s); store uploads alone are never "
            "treated as activation history.",
        )

        # AutotuneCore fixtures exercise prepared inputs, not the complete raw-data pipeline.
        parity_verified = False
        check("aaps_end_to_end_parity", parity_verified,
              "Component and prepared-input core comparisons exist. Raw treatment/profile reconstruction, preparation and total-IOB orchestration still require a source-bound end-to-end reference test.")
        result["parity_verified"] = parity_verified

        # Insulin configuration evidence
        config_rows = conn.execute(
            "SELECT remote_id,revision_hash,event_ms,payload_json,is_valid FROM raw_records WHERE source_id=? AND collection='devicestatus' AND is_current=1 AND event_ms<? AND json_type(payload_json,'$.configuration') IS NOT NULL",
            (source, end),
        ).fetchall()
        missing_configs = {
            row[0]
            for row in conn.execute(
                "SELECT remote_id FROM sync_disappearances WHERE source_id=? AND collection='devicestatus' AND resolved_ms IS NULL",
                (source,),
            )
        }
        insulin_evidence = insulin_configuration_evidence(
            [
                dict(row, presence_unknown=row["remote_id"] in missing_configs or not row["is_valid"])
                for row in config_rows
            ],
            start,
            end,
        )
        result["insulin_configuration_evidence"] = insulin_evidence
        observations = insulin_evidence["observations"]
        result["counts"]["configuration_uploads"] = len(observations)
        result["counts"]["resolved_peak_observations"] = insulin_evidence["resolved_peak_observations"]

        check(
            "historical_insulin_configuration",
            len(observations) > 0,
            f"{len(observations)} dated configuration uploads; {insulin_evidence['resolved_peak_observations']} with resolved peaks.",
        )

        # Device loop modes for eligibility, without silent defaults: raw
        # upload keys are tri-state (True/False/None unknown), and an explicit
        # user confirmation overrides an absent upload as user-reported.
        raw_configuration = getattr(snapshot, "configuration", None)
        if not isinstance(raw_configuration, dict):
            raw_configuration = {}
        user_confirmations_early = settings.get("user_confirmations", {}) if settings else {}
        if not isinstance(user_confirmations_early, dict):
            user_confirmations_early = {}
        def _tri_bool(value):
            return value if isinstance(value, bool) else None

        autosens = _tri_bool(raw_configuration.get("autosens_enabled"))
        autosens_source = "dated upload" if autosens is not None else None
        aps_configuration = raw_configuration.get("apsConfiguration")
        aps_configuration = aps_configuration if isinstance(aps_configuration, dict) else {}
        dynamic_isf = _tri_bool(aps_configuration.get("use_dynamic_sensitivity", raw_configuration.get("use_dynamic_sensitivity")))
        dynamic_isf_source = "dated upload" if dynamic_isf is not None else None
        if isinstance(user_confirmations_early.get("autosens_enabled"), bool):
            autosens = user_confirmations_early["autosens_enabled"]
            autosens_source = "user-reported"
        if isinstance(user_confirmations_early.get("dynamic_isf"), bool):
            dynamic_isf = user_confirmations_early["dynamic_isf"]
            dynamic_isf_source = "user-reported"
        plugin_name = None
        plugin_at_ms = None
        for observation in observations:
            if observation["event_ms"] < end and observation.get("plugin_name"):
                plugin_name = observation["plugin_name"]
                plugin_at_ms = observation["event_ms"]
        device_config = {
            "autosens_enabled": autosens,
            "autosens_source": autosens_source,
            "dynamic_isf": dynamic_isf,
            "dynamic_isf_source": dynamic_isf_source,
            "insulin_plugin": plugin_name,
            "insulin_plugin_at_ms": plugin_at_ms,
            "inspected_keys": ["autosens_enabled", "use_dynamic_sensitivity"],
            "configuration_at_ms": getattr(snapshot, "configuration_at_ms", None),
        }
        result["device_config"] = device_config

        # Build and run autotune
        throw_if_cancelled(cancelled)
        announce("Reconstructing profiles and delivery…")
        t_snapshot = time.perf_counter()
        analysis_snapshot = build_analysis_snapshot(conn, source, start, end, timezone, cancelled)

        if analysis_snapshot is None:
            check("autotune_input", False, "Could not build autotune input: missing baseline profile.")
            result["message"] = "Basal changes withheld: missing baseline profile."
            return result

        check("autotune_input", True, f"Built autotune input with {len(analysis_snapshot.analysis_days)} analysis days.")

        result["baseline_evidence"] = analysis_snapshot.baseline_evidence
        baseline = analysis_snapshot.baseline_profile
        pump_profile = analysis_snapshot.pump_profile
        # DIA/peak provenance: the profile store states DIA but never peak
        # (verified pure-JSON schema); peak resolves from dated device-status
        # insulin evidence. A stated store value always wins; device-status
        # supplies peak only when it is single-valued across the range.
        # Anything genuinely unknown keeps failing closed below.
        store_peak_stated = baseline.peak > 0
        in_range_clean = [
            observation
            for observation in observations
            if start <= observation["event_ms"] < end
            and not observation["issues"]
            and observation["peak_minutes"] is not None
        ]
        range_peaks = {observation["peak_minutes"] for observation in in_range_clean}
        peak_origin = None
        if len(range_peaks) == 1:
            latest = max(in_range_clean, key=lambda o: (o["event_ms"], o["remote_id"]))
            peak_origin = latest["peak_origin"]
            for profile in (baseline, pump_profile):
                if profile.peak <= 0:
                    profile.peak = latest["peak_minutes"]
                    from bganalyzer.autotune.models import LocalInsulin

                    profile.localInsulin = LocalInsulin(None, profile.peak, profile.dia)
        result["insulin_provenance"] = {
            "baseline_dia_hours": baseline.dia,
            "baseline_dia_source": "profile store" if baseline.dia > 0 else "unknown",
            "baseline_peak_minutes": baseline.peak,
            "baseline_peak_source": (
                "profile store"
                if store_peak_stated
                else (f"dated device-status ({peak_origin})" if peak_origin else "unknown")
            ),
            "in_range_peak_values": sorted(range_peaks),
            "in_range_resolved_peak_observations": len(in_range_clean),
        }
        if baseline.dia <= 0 or baseline.peak <= 0:
            missing = []
            if baseline.dia <= 0:
                missing.append("DIA missing from profile store")
            if baseline.peak <= 0:
                if len(range_peaks) > 1:
                    missing.append(
                        f"peak changed mid-range {sorted(range_peaks)}: no single epoch value"
                    )
                elif not in_range_clean:
                    missing.append("no clean in-range device-status peak evidence")
                else:
                    missing.append("peak unresolved")
            check(
                "autotune_input",
                False,
                "; ".join(missing)
                + "; tuning requires dated device-status evidence, not profile-store defaults.",
            )
            result["message"] = "Basal changes withheld: insulin DIA/peak unresolved."
            return result

        from bganalyzer.autotune.orchestration import resolve_daily_insulin
        invalid_days = resolve_daily_insulin(analysis_snapshot, observations)
        result["historical_insulin_exclusions"] = invalid_days
        check("daily_insulin_parameters", not invalid_days,
              f"{len(invalid_days)} days excluded because historical insulin settings could not be resolved.")
        result["timings"]["snapshot_s"] = round(time.perf_counter() - t_snapshot, 3)
        throw_if_cancelled(cancelled)
        t_autotune = time.perf_counter()
        autotune_output = run_full_autotune(analysis_snapshot, cancelled, announce)
        result["timings"]["autotune_s"] = round(time.perf_counter() - t_autotune, 3)

        if not analysis_snapshot.analysis_days:
            result["descriptive_candidates"] = [{
                "family": "isf", "segment": "global", "baseline_value": baseline.isf,
                "proposed_value": None, "status": "insufficient_evidence", "confidence": "low",
                "supported": False, "direction": "unavailable",
                "reason": "No complete days under the current settings with matching insulin lookback.",
            }]
            from bganalyzer.autotune.profile_period import no_analysis_days_message
            result["message"] = no_analysis_days_message(analysis_snapshot.baseline_evidence, timezone)
            check("autotune_input", False, result["message"])
            return result

        # Check eligibility
        throw_if_cancelled(cancelled)
        announce("Checking eligibility…")
        t_eligibility = time.perf_counter()
        eligibility_checker = EligibilityChecker()
        glucose_readings = [
            {"timestamp": g["timestamp"], "value": g["value"]}
            for day in analysis_snapshot.analysis_days
            for g in day.glucose
        ]

        # Eligibility inputs share the overlaid pump profile.
        user_confirmations = user_confirmations_early

        # Policy is needed both for the descriptive low-confidence path below
        # and for the numerical release gate that follows eligibility.
        from bganalyzer.recommendations.policy import (
            get_policy,
            DEFAULT_POLICY_V1,
            validated_policy_audit,
            policy_fingerprint,
        )
        policy = get_policy(
            settings.get("policy_version", "policy-v1") if settings else "policy-v1"
        )

        # Real timelines for eligibility: the profile timeline now carries
        # derived inferred activations; the delivery timeline has partial
        # verification with temp-basal splitting and gap filling.
        from bganalyzer.timeline.insulin import build_delivery_timeline
        from bganalyzer.timeline.profiles import build_profile_timeline

        profile_timeline = build_profile_timeline(conn, source, end, start)
        delivery_timeline = build_delivery_timeline(conn, source, start, end, profile_timeline)

        # Now perform actual delivery verification with the built timeline
        delivery_quality = "unknown"
        delivery_issues = []

        try:
            if delivery_timeline:
                intervals = delivery_timeline.resolve_delivery(start, end)
                if intervals:
                    # Check for unknown/conflicted quality intervals
                    uncertain_intervals = [d for d in intervals if d.quality in ("uncertain", "conflicted")]
                    unknown_intervals = [d for d in intervals if d.origin == DeliveryOrigin.UNKNOWN]

                    if uncertain_intervals:
                        delivery_issues.append(f"{len(uncertain_intervals)} uncertain/conflicted intervals")
                    if unknown_intervals:
                        delivery_issues.append(f"{len(unknown_intervals)} unknown-origin intervals")

                    # Check for assumed vs confirmed quality
                    assumed_intervals = [d for d in intervals if d.quality == "assumed"]
                    confirmed_intervals = [d for d in intervals if d.quality == "confirmed"]

                    if not delivery_issues and not assumed_intervals:
                        delivery_quality = "verified"
                        delivery_issues.append(f"{len(intervals)} fully confirmed intervals")
                    elif not delivery_issues and assumed_intervals:
                        delivery_quality = "acceptable"
                        delivery_issues.append(f"{len(confirmed_intervals)} confirmed, {len(assumed_intervals)} assumed intervals")
                    else:
                        delivery_quality = "partial"
                else:
                    delivery_issues.append("no delivery intervals in range")
                    delivery_quality = "missing"
            else:
                delivery_issues.append("delivery timeline not built")
                delivery_quality = "missing"
        except Exception as e:
            delivery_issues.append(f"delivery resolution error: {str(e)}")
            delivery_quality = "error"

        # Accept verified and acceptable quality for use. Assumed scheduled
        # delivery (no temp basal recorded) is reported, not a blocker: it is
        # a sync-coverage matter, not a reconstruction failure. Only
        # unknown/conflicted intervals fail closed, matching the eligibility
        # check in recommendations.eligibility._check_delivery_reconstruction.
        delivery_verified = delivery_quality in ("verified", "acceptable")
        check(
            "delivery_verification",
            delivery_verified,
            f"Delivery reconstruction: {delivery_quality}. " +
            "; ".join(delivery_issues) +
            ". Assumed intervals do not establish pump-confirmed delivery; this requires "
            "validation of cancellations and suspensions.",
        )

        eligibility = eligibility_checker.check_eligibility(
            autotune_output=autotune_output,
            profile_timeline=profile_timeline,
            delivery_timeline=delivery_timeline,
            sync_quality=quality,
            glucose_readings=glucose_readings,
            user_confirmations=user_confirmations,
            current_time_ms=int(datetime.now().timestamp() * 1000),
            start_ms=start,
            end_ms=end,
            device_config=device_config,
        )

        result["eligibility"] = {
            "status": eligibility.status.value,
            "reason_codes": [rc.value for rc in eligibility.reason_codes],
            "supported_families": eligibility.supported_families,
            "details": eligibility.details,
        }
        result["timings"]["eligibility_s"] = round(time.perf_counter() - t_eligibility, 3)

        # Check if eligible
        if eligibility.status != EligibilityStatus.ELIGIBLE:
            result["status"] = "withheld"
            result["message"] = f"Basal changes withheld: eligibility = {eligibility.status.value}"
            for rc in eligibility.reason_codes:
                check(f"eligibility_{rc.value.lower()}", False, f"Eligibility blocked: {rc.value}")

            # The autotune run already produced a final profile. When the run
            # completed but the data gates withheld the numerical release, the
            # raw deviation is still worth surfacing as a low-confidence
            # descriptive suggestion: it is the same numbers the full pipeline
            # would have validated, just without the evidence to stand behind
            # them. Nothing here is pump-enterable; every candidate is marked
            # explicitly and the reason codes are attached.
            result["descriptive_candidates"] = _generate_candidates(
                autotune_output,
                analysis_snapshot.baseline_profile,
                policy,
                eligibility,
                confidence="low",
                reason_codes=[rc.value for rc in eligibility.reason_codes],
            )
            result["candidate_grid"] = _candidate_grid(
                result["descriptive_candidates"], confidence="low"
            )
            return result

        # Policy validation - clinical gate must pass before numerical output
        if policy is None:
            result["message"] = "Basal changes withheld: no release policy installed."
            check("policy_installed", False, "No numerical release policy found.")
            return result

        # Validate context
        context_ok, context_msg = policy.validate_context(
            settings.get("context", "adult_t1d_novorapid_omnipod_aaps34") if settings else "adult_t1d_novorapid_omnipod_aaps34",
            pump_profile.localInsulin.name or "unknown",
            pump_profile.peak,
            pump_profile.dia,
        )
        check("policy_context", context_ok, context_msg)

        if not context_ok:
            result["message"] = f"Basal changes withheld: policy context invalid - {context_msg}"
            return result

        validated = validated_policy_audit(policy)
        result["policy_hash"] = policy_fingerprint(policy)
        check("numerical_release_policy", validated, "Release audit must match the current policy and the hashes of every evidence artifact.")
        if not validated or not parity_verified:
            result["message"] = "Basal changes withheld: release validation is incomplete."
            return result
        candidates = _generate_candidates(autotune_output, analysis_snapshot.baseline_profile, policy, eligibility)
        ready, descriptive = partition_candidates(candidates)
        result["recommendations"] = ready
        result["descriptive_candidates"] = descriptive
        result["candidate_grid"] = _candidate_grid(candidates, confidence="full")
        result["status"] = "eligible" if ready else "withheld"
        result["message"] = (f"{len(ready)} candidates passed all release checks; "
                             f"{len(descriptive)} remain descriptive or rejected. "
                             f"Analysis used {len(autotune_output.tuned_days)} tuned days.")

    finally:
        conn.rollback()

    return result


def partition_candidates(candidates):
    ready, descriptive = [], []
    for candidate in candidates:
        eligible = (candidate.get('status') == 'candidate' and candidate.get('confidence') == 'full'
                    and candidate.get('supported') is True
                    and (candidate.get('family') != 'basal'
                         or candidate.get('hourly_support', {}).get('numerical_release_ready') is True))
        (ready if eligible else descriptive).append(candidate)
    return ready, descriptive


def _generate_candidates(
    autotune_output,
    baseline_profile,
    policy: NumericalReleasePolicy,
    eligibility=None,
    confidence: str = "full",
    reason_codes: list | None = None,
):
    """Generate recommendation candidates from autotune output.

    Applies policy bounds and quantization to produce pump-enterable values.

    Each candidate is annotated with:
      - contributing_days: number of tuned days that backed the estimate
      - supported: whether the family had sufficient episode coverage (per §11)
      - sensitivity_min / sensitivity_max: LOO basal range bounds (basal only)
        derived from leave-one-day-out reruns; None when <2 days available
      - confidence: "full" when the eligibility pipeline cleared every data
        gate, or "low" when the same numbers are surfaced descriptively
        because a data gate withheld numerical release. Low-confidence
        candidates are never pump-enterable.
    """
    candidates = []

    if not autotune_output.tuned_days:
        return candidates

    low_confidence = confidence == "low"
    withholding_reasons = list(reason_codes or [])

    final = autotune_output.tuned_days[-1]
    baseline_basal = baseline_profile.basal
    tuned_basal = final.basal

    # --- derive annotation metadata from eligibility result ---
    supported_families: set[str] = set()
    sensitivity_ranges: dict = {}
    n_contributing_days: int = len(autotune_output.tuned_days)

    if eligibility is not None:
        # supported_families is the pre-computed episode-support list from check_eligibility
        supported_families = set(getattr(eligibility, "supported_families", []) or [])
        # sensitivity_ranges carries LOO per-parameter min/max from _check_sensitivity_stability
        sensitivity_ranges = (eligibility.details or {}).get("sensitivity_ranges", {})
        # contributing_days: count tuned eligible days from day_stats when available
        day_stats = list(getattr(autotune_output, "day_stats", None) or [])
        if day_stats:
            n_contributing_days = sum(1 for s in day_stats if s.get("tuned", False))

    basal_loo_ranges: dict = sensitivity_ranges.get("basal_ranges", {})


    # Generate basal candidates (hourly)
    basal_supported = "basal" in supported_families
    for hour in range(24):
        baseline_rate = baseline_basal[hour]
        tuned_rate = tuned_basal[hour]

        if abs(tuned_rate - baseline_rate) < 0.001:
            continue  # No change

        # Validate against policy
        ok, msg = policy.validate_basal_change(baseline_rate, tuned_rate)
        if not ok:
            candidates.append({
                "family": "basal",
                "segment": hour,
                "time": f"{hour:02d}:00",
                "baseline_value": baseline_rate,
                "proposed_value": tuned_rate,
                "direction": "n/a",
                "status": "rejected",
                "reason": msg,
                "confidence": confidence,
                "reason_codes": withholding_reasons,
            })
            continue

        # Quantize to pump increment
        quantized = policy.quantize_basal(tuned_rate)

        # Re-validate quantized value
        ok, msg = policy.validate_basal_change(baseline_rate, quantized)
        if not ok:
            candidates.append({
                "family": "basal",
                "segment": hour,
                "time": f"{hour:02d}:00",
                "baseline_value": baseline_rate,
                "proposed_value": quantized,
                "direction": "n/a",
                "status": "rejected",
                "reason": f"Quantized value rejected: {msg}",
                "confidence": confidence,
                "reason_codes": withholding_reasons,
            })
            continue

        # Quantization can round the deviation back onto the baseline (e.g.
        # 1.5001 U/hr with a 0.05 U/hr pump step). That is no change, not a
        # decrease, so skip it rather than advertising a zero-magnitude move.
        if abs(quantized - baseline_rate) < 0.001:
            continue

        # LOO sensitivity bounds for this hour (None when <2 days available)
        loo_hour = basal_loo_ranges.get(hour)
        sensitivity_min = loo_hour["min"] if loo_hour else None
        sensitivity_max = loo_hour["max"] if loo_hour else None

        candidates.append({
            "family": "basal",
            "segment": hour,
            "time": f"{hour:02d}:00",
            "baseline_value": baseline_rate,
            "proposed_value": quantized,
            "raw_value": tuned_rate,
            "direction": "increase" if quantized > baseline_rate else "decrease",
            "status": "candidate",
            "contributing_days": n_contributing_days,
            "supported": basal_supported,
            "sensitivity_min": sensitivity_min,
            "sensitivity_max": sensitivity_max,
            "confidence": confidence,
            "reason_codes": withholding_reasons,
        })


    # Generate IC candidate (scalar)
    baseline_ic = baseline_profile.ic
    tuned_ic = final.ic

    ic_supported = "ic" in supported_families
    ic_loo_range = sensitivity_ranges.get("ic_range")
    if abs(tuned_ic - baseline_ic) >= 0.001:
        ok, msg = policy.validate_ic_change(baseline_ic, tuned_ic)
        if ok:
            quantized = policy.quantize_ic(tuned_ic)
            ok, msg = policy.validate_ic_change(baseline_ic, quantized)
            if ok:
                candidates.append({
                    "family": "ic",
                    "segment": "global",
                    "baseline_value": baseline_ic,
                    "proposed_value": quantized,
                    "raw_value": tuned_ic,
                    "direction": "unchanged" if quantized == baseline_ic else "increase" if quantized > baseline_ic else "decrease",
                    "status": "unchanged" if quantized == baseline_ic else "candidate",
                    "contributing_days": n_contributing_days,
                    "supported": ic_supported,
                    "sensitivity_min": ic_loo_range["min"] if ic_loo_range else None,
                    "sensitivity_max": ic_loo_range["max"] if ic_loo_range else None,
                    "confidence": confidence,
                    "reason_codes": withholding_reasons,
                })
            else:
                candidates.append({
                    "family": "ic",
                    "segment": "global",
                    "time": None,
                    "baseline_value": baseline_ic,
                    "proposed_value": tuned_ic,
                    "direction": "n/a",
                    "status": "rejected",
                    "reason": f"Quantized IC rejected: {msg}",
                    "confidence": confidence,
                    "reason_codes": withholding_reasons,
                })
        else:
            candidates.append({
                "family": "ic",
                "segment": "global",
                "time": None,
                "baseline_value": baseline_ic,
                "proposed_value": tuned_ic,
                "direction": "n/a",
                "status": "rejected",
                "reason": msg,
                "confidence": confidence,
                "reason_codes": withholding_reasons,
            })


    else:
        candidates.append({
            "family": "ic", "segment": "global",
            "baseline_value": baseline_ic, "proposed_value": baseline_ic,
            "raw_value": tuned_ic, "direction": "unchanged", "status": "unchanged",
            "contributing_days": n_contributing_days, "supported": ic_supported,
            "confidence": confidence, "reason_codes": withholding_reasons,
        })

    # Generate ISF candidate (scalar)
    # ISF is always supported=False per §11: reference defines no correction episodes.
    baseline_isf = baseline_profile.isf
    tuned_isf = final.isf
    isf_loo_range = sensitivity_ranges.get("isf_range")
    isf_limitation = (eligibility.details or {}).get("isf_limitation") if eligibility else None

    if abs(tuned_isf - baseline_isf) >= 0.001:
        ok, msg = policy.validate_isf_change(baseline_isf, tuned_isf)
        if ok:
            quantized = policy.quantize_isf(tuned_isf)
            ok, msg = policy.validate_isf_change(baseline_isf, quantized)
            if ok:
                if abs(quantized - baseline_isf) < 0.001:
                    pass  # quantization rounded the change back onto baseline
                else:
                    candidates.append({
                        "family": "isf",
                        "segment": "global",
                        "baseline_value": baseline_isf,
                        "proposed_value": quantized,
                        "raw_value": tuned_isf,
                        "direction": "increase" if quantized > baseline_isf else "decrease",
                        "status": "candidate",
                        "contributing_days": n_contributing_days,
                        "supported": False,  # ISF always unsupported: no correction episodes in reference
                        "isf_limitation": isf_limitation or "reference defines no correction episodes; numeric ISF withheld",
                        "sensitivity_min": isf_loo_range["min"] if isf_loo_range else None,
                        "sensitivity_max": isf_loo_range["max"] if isf_loo_range else None,
                        "confidence": confidence,
                        "reason_codes": withholding_reasons,
                    })
            else:
                candidates.append({
                    "family": "isf",
                    "segment": "global",
                    "time": None,
                    "baseline_value": baseline_isf,
                    "proposed_value": tuned_isf,
                    "direction": "n/a",
                    "status": "rejected",
                    "reason": f"Quantized ISF rejected: {msg}",
                    "confidence": confidence,
                    "reason_codes": withholding_reasons,
                })
        else:
            candidates.append({
                "family": "isf",
                "segment": "global",
                "time": None,
                "baseline_value": baseline_isf,
                "proposed_value": tuned_isf,
                "direction": "n/a",
                "status": "rejected",
                "reason": msg,
                "confidence": confidence,
                "reason_codes": withholding_reasons,
            })


    if not any(c["family"] == "isf" for c in candidates):
        candidates.append({
            "family": "isf", "segment": "global", "baseline_value": baseline_isf,
            "proposed_value": baseline_isf, "raw_value": tuned_isf,
            "status": "unchanged", "direction": "unchanged", "supported": False,
            "confidence": confidence, "reason_codes": withholding_reasons,
        })

    from bganalyzer.analytics.candidate_details import attach_basal_evidence

    attach_basal_evidence(candidates, autotune_output, baseline_profile, policy)
    return candidates


def _candidate_grid(candidates, confidence="full"):
    """Fold a candidate list into a compact grid keyed by family and segment.

    The full report is a wall of text; the suggestions are the part the user
    actually acts on. This gathers every candidate into one structure keyed by
    ("basal", hour), ("ic", "global"), ("isf", "global") so the UI can render a
    table instead of a paragraph. Rejected entries keep their reason so the
    grid is self-explanatory.
    """
    grid = {}
    for c in candidates or []:
        family = c.get("family")
        segment = c.get("segment")
        if family == "basal":
            key = ("basal", int(segment))
        elif family in ("ic", "isf"):
            key = (family, "global")
        else:
            key = (family, str(segment))
        grid[key] = {
            "family": family,
            "segment": segment,
            "time": c.get("time"),
            "baseline_value": c.get("baseline_value"),
            "proposed_value": c.get("proposed_value"),
            "raw_value": c.get("raw_value"),
            "direction": c.get("direction"),
            "status": c.get("status"),
            "reason": c.get("reason"),
            "contributing_days": c.get("contributing_days"),
            "supported": c.get("supported"),
            "sensitivity_min": c.get("sensitivity_min"),
            "sensitivity_max": c.get("sensitivity_max"),
            "confidence": c.get("confidence", confidence),
            "reason_codes": c.get("reason_codes", []),
            "hourly_support": c.get("hourly_support"),
        }
    return {f"{family}:{segment}": v for (family, segment), v in sorted(grid.items())}


def _merge_basal_ranges(candidates):
    """Merge consecutive basal hours that share the same proposed rate.

    A pump profile is entered as one rate per hour, but a flat segment such as
    hours 20-23 all moving to 1.325 U/hr reads better as a range than as four
    identical rows. Only candidate rows are merged; rejected rows are emitted
    individually since each carries its own reason.
    """
    basal = sorted(
        (c for c in candidates or [] if c.get("family") == "basal"
         and c.get("status") == "candidate"),
        key=lambda c: int(c.get("segment", 0)),
    )
    merged = []
    for c in basal:
        hour = int(c.get("segment", 0))
        # Group on the rounded two-decimal rate that the pump actually
        # accepts, not the raw quantized float. Exact float equality between
        # values that both went through round(x, 2) can still differ by a
        # ULP, which would otherwise split one flat segment into two rows.
        proposed = round(float(c.get("proposed_value", 0)), 2)
        if merged and merged[-1]["end"] == hour - 1 \
                and abs(merged[-1]["proposed"] - proposed) < 1e-9:
            merged[-1]["end"] = hour
            continue
        merged.append({
            "start": hour,
            "end": hour,
            "proposed": proposed,
            "baseline": round(float(c.get("baseline_value", 0)), 2),
            "direction": c.get("direction"),
            "status": c.get("status"),
        })

    # Build one time-ordered list. Merged candidates come first, then rejected
    # basal entries, then the IC/ISF scalars — all sorted by hour so a gap
    # between hours 1 and 4 is visible rather than hidden at the end.
    rows = []
    for m in merged:
        if m["start"] == m["end"]:
            rows.append({**m, "range": f"Basal {m['start']:02d}:00"})
        else:
            rows.append({**m, "range": f"Basal {m['start']:02d}:00–{m['end']:02d}:00"})
    for c in candidates or []:
        if c.get("family") == "basal" and c.get("status") == "rejected":
            rows.append({
                "start": int(c.get("segment", 0)),
                "end": int(c.get("segment", 0)),
                "proposed": round(float(c.get("proposed_value", 0)), 2),
                "baseline": round(float(c.get("baseline_value", 0)), 2),
                "direction": c.get("direction"),
                "status": c.get("status"),
                "range": f"Basal {int(c.get('segment', 0)):02d}:00",
            })
    rows.sort(key=lambda r: r.get("start") if r.get("start") is not None else 99)

    # IC and ISF scalars pass through unchanged, appended after the hourly rows.
    for c in candidates or []:
        if c.get("family") in ("ic", "isf"):
            rows.append({
                "start": None,
                "end": None,
                "proposed": c.get("proposed_value"),
                "baseline": c.get("baseline_value"),
                "direction": c.get("direction"),
                "status": c.get("status"),
                "range": f"{c.get('family', '').upper()} (global)",
            })
    return rows


def format_readiness(result):
    """Format readiness check results for display."""
    if not isinstance(result, dict):
        return f"Internal error: format_readiness received non-dict result: {type(result).__name__} = {result!r}"
    lines = [result.get("message", ""), ""]
    start_ms, end_ms = result.get("start_ms"), result.get("end_ms")
    if start_ms is not None and end_ms is not None:
        zone = ZoneInfo(result.get("timezone", "UTC"))
        lo = datetime.fromtimestamp(start_ms / 1000, zone).strftime("%d %b %Y")
        hi = datetime.fromtimestamp(end_ms / 1000, zone).strftime("%d %b %Y")
        days = round((end_ms - start_ms) / 86400000)
        lines.append(f"Analyzing: {lo} → {hi} ({days} days). Change Range for another period.")
        lines.append("")
    findings = result.get("descriptive_findings") or []
    if findings:
        lines.append(
            "Recurring low-glucose observations (descriptive grouping only — "
            "not dosing advice, and co-occurrence is not proof of cause):"
        )
        for finding in findings:
            lines.append(
                f"  {finding['bucket_start']}–{finding['bucket_end']} local time · "
                f"below {finding['low_threshold_mgdl']:.0f} mg/dL on "
                f"{len(finding['contributing_days'])} days "
                f"({', '.join(finding['contributing_days'])}) · "
                f"{finding['episode_count']} episodes [{finding['rule_version']}]"
            )
            for ep in finding["episodes"]:
                lines.append(
                    f"    {ep['date']} {ep['start']} · {ep['covered_minutes']} covered min · "
                    f"lowest {ep['min_mgdl']} mg/dL"
                )
            if finding["days_with_readings_no_episode"]:
                lines.append(
                    "    Days with readings here but no low episode: "
                    + ", ".join(finding["days_with_readings_no_episode"])
                )
        lines.append("")
    timings = result.get("timings") or {}
    if timings:
        lines.append(
            "Compute time: "
            + ", ".join(f"{k}={v}s" for k, v in sorted(timings.items()))
        )
        lines.append("")
    for item in result.get("checks", []):
        lines.append(
            ("PASS" if item["passed"] else "BLOCKED")
            + " · "
            + item["code"]
            + "\n"
            + item["detail"]
            + "\n"
        )

    sync_quality = result.get("sync_quality") or {}
    unchecked = {
        collection: sync_quality.get(collection, {}).get("missing_windows", [])
        for collection in ("entries", "treatments", "devicestatus")
    }
    if any(unchecked.values()):
        zone = ZoneInfo(result.get("timezone", "UTC"))
        lines.append("Unchecked import windows (re-run Sync report period for these):")
        for collection in ("entries", "treatments", "devicestatus"):
            windows = unchecked[collection]
            for lo, hi in windows[:2]:
                lo_s = datetime.fromtimestamp(lo / 1000, zone).strftime("%d %b %H:%M:%S")
                hi_s = datetime.fromtimestamp(hi / 1000, zone).strftime("%d %b %H:%M:%S")
                lines.append(f"  {collection}: {lo_s} → {hi_s}")
            if len(windows) > 2:
                lines.append(f"  {collection}: …and {len(windows) - 2} further intervals")
        lines.append("")

    # Show insulin configuration evidence (always displayed when available)
    evidence = result.get("insulin_configuration_evidence", {})
    observations = evidence.get("observations", [])
    if observations:
        zone = ZoneInfo(result.get("timezone", "UTC"))
        lines.append("Dated insulin configuration evidence (earliest/latest uploads):")
        shown = observations if len(observations) <= 10 else observations[:5] + observations[-5:]
        for o in shown:
            stamp = datetime.fromtimestamp(o["event_ms"] / 1000, zone).strftime(
                "%d %b %Y %H:%M:%S %Z (%z)"
            )
            lines.append(f"  {stamp} · record {o['remote_id']} · revision {o['revision_hash']}")
            lines.append(
                f"  AAPS {o['version'] or 'unknown'} · plugin {o['plugin_name'] or 'unknown'}"
            )
            if o["peak_minutes"] is not None:
                lines.append(f"  Peak {o['peak_minutes']} minutes · {o['peak_origin']}")
            if o["issues"]:
                lines.append("  Unresolved: " + ", ".join(o["issues"]))
        if len(observations) > 10:
            lines.append(
                f"  …{len(observations) - 10} further uploads omitted from display; "
                "all remain in the stored evidence."
            )
        if evidence.get("issue_counts"):
            lines.append(
                "Historical upload issues: "
                + ", ".join(f"{k}: {v}" for k, v in sorted(evidence["issue_counts"].items()))
            )
        lines.append("")

    # Show eligibility
    eligibility = result.get("eligibility", {})
    if eligibility:
        lines.append(f"Eligibility: {eligibility.get('status', 'unknown')}")
        if eligibility.get("reason_codes"):
            lines.append("Reason codes: " + ", ".join(eligibility["reason_codes"]))
        if eligibility.get("supported_families"):
            lines.append("Supported families: " + ", ".join(eligibility["supported_families"]))
        lines.append("")

    device_config = result.get("device_config") or {}
    if device_config:
        def _mode(value, source):
            if value is not None:
                return f"{value} ({source})"
            return f"unknown ({source or 'not stated by uploads'})"

        lines.append(
            "Loop modes: autosens="
            + _mode(device_config.get("autosens_enabled"), device_config.get("autosens_source"))
            + "; dynamic ISF="
            + _mode(device_config.get("dynamic_isf"), device_config.get("dynamic_isf_source"))
            + "; insulin plugin="
            + str(device_config.get("insulin_plugin") or "unknown")
            + ". Unknown stays descriptive-only until confirmed."
        )
        lines.append("")

    # Show candidates
    candidates = result.get("recommendations", [])
    if candidates:
        lines.append("Candidates:")
        for c in candidates:
            if c.get("family") == "basal":
                lines.append(
                    f"  Basal {c['time']}: {c['baseline_value']:.3f} → {c['proposed_value']:.3f} U/hr "
                    f"({c['direction']}) [{c['status']}]"
                )
            elif c.get("family") == "ic":
                if c.get("proposed_value") is None:
                    lines.append("  IC (global): insufficient meal evidence; no proposed ratio.")
                    continue
                lines.append(
                    f"  IC (global): {c['baseline_value']:.1f} → {c['proposed_value']:.1f} g/U "
                    f"({c['direction']}) [{c['status']}]"
                )
            elif c.get("family") == "isf":
                if c.get("proposed_value") is None:
                    lines.append("  ISF (global): insufficient current-profile evidence; no proposed value.")
                    continue
                lines.append(
                    f"  ISF (global): {c['baseline_value']:.1f} → {c['proposed_value']:.1f} mg/dL/U "
                    f"({c['direction']}) [{c['status']}]"
                )
        lines.append("")

    # Show candidates as a compact grid. Consecutive hours sharing the same
    # proposed rate are merged into a range (e.g. hours 20-23 at 1.325 U/hr)
    # rather than listing four identical rows.
    candidates = result.get("recommendations", [])
    descriptive = result.get("descriptive_candidates", [])
    if candidates or descriptive:
        lines.append("Basal suggestions (confidence=full):")
        for label, conf in (("candidates", "full"), ("descriptive_candidates", "low")):
            rows = candidates if label == "candidates" else descriptive
            if not rows:
                continue
            lines.append(f"  [{label}]")
            merged = _merge_basal_ranges(rows)
            for row in merged:
                proposed = f"{row['proposed']:.3f}" if row['proposed'] is not None else "Unavailable"
                unit = "g/U" if row['range'].startswith("IC ") else "mg/dL/U" if row['range'].startswith("ISF ") else "U/hr"
                lines.append(f"    {row['range']}: {row['baseline']:.3f} → {proposed} {unit} ({row['direction']}) [{row['status']}]")
            lines.append("")
        lines.append("")

    # Show gaps
    gaps = result.get("profile_evidence_coverage", {}).get("gaps", [])
    if gaps:
        zone = ZoneInfo(result.get("timezone", "UTC"))
        lines.append("Missing switch evidence (no effective Note or Profile Switch upload):")
        for gap in gaps:
            lo, hi = (
                datetime.fromtimestamp(gap[key] / 1000, zone).strftime("%d %b %Y %H:%M:%S %Z (%z)")
                for key in ("start_ms", "end_ms")
            )
            lines.append(f"  {lo} → {hi}")
        lines.append("")

    counts = result.get("counts", {})
    bearing = counts.get("profile_bearing_by_event") or {}
    if bearing or counts.get("profile_store_versions"):
        lines.append(
            f"Profile sources synced: {counts.get('profile_store_versions', 0)} store version(s); "
            + (
                "switch uploads in range: "
                + ", ".join(f"{total}× {kind}" for kind, total in sorted(bearing.items()))
                if bearing
                else "no switch uploads in range"
            )
            + ". Without switch uploads there is no activation evidence to tune from."
        )
        lines.append("")

    switch_diagnosis = result.get("switch_diagnosis") or []
    if switch_diagnosis:
        lines.append("Switch-upload verdicts (why each record does or does not give evidence):")
        lines.extend(switch_diagnosis[:25])
        if len(switch_diagnosis) > 25:
            lines.append(f"  …and {len(switch_diagnosis) - 25} further records")
        lines.append("")

    provenance = result.get("insulin_provenance") or {}
    if provenance:
        lines.append(
            f"Insulin configuration for tuning: DIA {provenance.get('baseline_dia_hours')}h "
            f"({provenance.get('baseline_dia_source')}), peak "
            f"{provenance.get('baseline_peak_minutes')}min "
            f"({provenance.get('baseline_peak_source')}); "
            f"{provenance.get('in_range_resolved_peak_observations', 0)} clean in-range "
            "peak observations."
        )
        lines.append("")

    if not candidates:
        if result.get("status") == "withheld":
            lines.append("No basal rate changes were calculated.")
            lines.append("A blocked result is not a recommendation to leave current settings unchanged.")
        else:
            lines.append("No numerical candidates were produced by this analysis.")
    return "\n".join(lines)
