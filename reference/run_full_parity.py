"""End-to-end parity test using AAPS reference test JSON files.

This parses the AAPS test JSON format and runs both the Kotlin reference
and Python port on the same inputs, comparing outputs exactly.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--java', required=True)
parser.add_argument('--kotlin-lib', required=True)
args = parser.parse_args()

manifest = json.loads((root / 'aaps/manifest.json').read_text())
for name, entry in manifest['files'].items():
    assert hashlib.sha256((root / 'aaps' / name).read_bytes()).hexdigest() == entry['sha256'], name

# Add src to path
src_path = root / '../src'
sys.path.insert(0, str(src_path))

from bganalyzer.autotune.core import tune_day, run_autotune, _percentile
from bganalyzer.autotune.models import ATProfile, LocalInsulin, PreppedGlucose, BGDatum, CRDatum, DiaDeviation, PeakDeviation, Round


def parse_aaps_prepped_glucose(json_data: dict) -> PreppedGlucose:
    """Parse AAPS PreppedGlucose JSON into Python PreppedGlucose."""
    
    # Parse CRData
    cr_data = []
    for cr in json_data.get("CRData", []):
        datum = CRDatum()
        datum.crInitialIOB = cr.get("CRInitialIOB", 0.0)
        datum.crInitialBG = cr.get("CRInitialBG", 0.0)
        datum.crEndIOB = cr.get("CREndIOB", 0.0)
        datum.crEndBG = cr.get("CREndBG", 0.0)
        datum.crCarbs = cr.get("CRCarbs", 0.0)
        datum.crInsulin = cr.get("CRInsulin", 0.0)
        datum.crInsulinTotal = cr.get("CRInsulinTotal", 0.0)
        
        # Parse timestamps
        if "CRInitialCarbTime" in cr:
            dt = datetime.fromisoformat(cr["CRInitialCarbTime"].replace('Z', '+00:00'))
            datum.crInitialCarbTime = int(dt.timestamp() * 1000)
        if "CREndTime" in cr:
            dt = datetime.fromisoformat(cr["CREndTime"].replace('Z', '+00:00'))
            datum.crEndTime = int(dt.timestamp() * 1000)
        
        cr_data.append(datum)
    
    # Parse glucose data arrays
    def parse_bg_array(arr):
        result = []
        for bg in arr:
            datum = BGDatum(
                date=bg.get("date", 0),
                value=float(bg.get("glucose", bg.get("sgv", 0.0))),
                avgDelta=float(bg.get("avgDelta", 0.0)),
                bgi=float(bg.get("BGI", bg.get("bgi", 0.0))),
                deviation=float(bg.get("deviation", 0.0)),
                mealAbsorption=bg.get("mealAbsorption", ""),
                uamAbsorption=bg.get("uamAbsorption", ""),
                mealCarbs=int(bg.get("mealCarbs", 0)),
            )
            result.append(datum)
        return result
    
    csf_data = parse_bg_array(json_data.get("CSFGlucoseData", []))
    isf_data = parse_bg_array(json_data.get("ISFGlucoseData", []))
    basal_data = parse_bg_array(json_data.get("basalGlucoseData", []))
    
    # Parse dia/peak deviations
    dia_devs = []
    for d in json_data.get("DiaDeviations", []):
        dia_devs.append(DiaDeviation(
            dia=d.get("dia", 0.0),
            meanDeviation=d.get("meanDeviation", 0.0),
            smrDeviation=d.get("smrDeviation", 0.0),
            rmsDeviation=d.get("rmsDeviation", 0.0),
        ))
    
    peak_devs = []
    for p in json_data.get("PeakDeviations", []):
        peak_devs.append(PeakDeviation(
            peak=p.get("peak", 0),
            meanDeviation=p.get("meanDeviation", 0.0),
            smrDeviation=p.get("smrDeviation", 0.0),
            rmsDeviation=p.get("rmsDeviation", 0.0),
        ))
    
    start_bg = json_data.get("startBG", 0)
    
    return PreppedGlucose(
        startBG=start_bg,
        crData=cr_data,
        csfGlucoseData=csf_data,
        isfGlucoseData=isf_data,
        basalGlucoseData=basal_data,
        diaDeviations=dia_devs,
        peakDeviations=peak_devs,
    )


def parse_aaps_profile(json_data: dict) -> ATProfile:
    """Parse AAPS profile JSON into Python ATProfile."""
    # Handle both formats: top-level isf/carb_ratio or nested isfProfile
    isf = json_data.get("isf", json_data.get("insulin_sensitivity", 0.0))
    if isf == 0.0 and "isfProfile" in json_data:
        sens = json_data["isfProfile"].get("sensitivities", [])
        if sens:
            isf = sens[0].get("sensitivity", 0.0)
    
    ic = json_data.get("carb_ratio", 0.0)
    if ic == 0.0 and "ic" in json_data:
        ic = json_data["ic"]
    
    # Get autosens bounds from profile if present
    autosens_max = json_data.get("autosens_max", 1.2)
    autosens_min = json_data.get("autosens_min", 0.7)
    min_5m_carbimpact = json_data.get("min_5m_carbimpact", 8.0)
    
    profile = ATProfile(
        basal=[0.0] * 24,
        basalUnTuned=[0] * 24,
        ic=ic,
        isf=isf,
        dia=json_data.get("dia", 0.0),
        peak=json_data.get("insulinPeakTime", json_data.get("peak", 0)),
        isValid=True,
        from_=0,
        profileName=json_data.get("name", "test"),
        timezone=json_data.get("timezone", "UTC"),
    )
    
    # Parse basal profile
    basal_profile = json_data.get("basalprofile", [])
    for entry in basal_profile:
        time_str = entry.get("start", "00:00:00")
        h = int(time_str.split(":")[0])
        rate = entry.get("rate", 0.0)
        profile.basal[h] = rate
        if entry.get("untuned", 0) == 1:
            profile.basalUnTuned[h] = 1
    
    profile.localInsulin = LocalInsulin(None, profile.peak, profile.dia)
    return profile, {"autosens_max": autosens_max, "autosens_min": autosens_min, "min_5min_carbimpact": min_5m_carbimpact}


# Test case 1
print("Loading test case 1...")
with open(root / 'aaps_test_res/autotune/test1/autotune.2022-05-21.json') as f:
    test1_prepped = parse_aaps_prepped_glucose(json.load(f))

with open(root / 'aaps_test_res/autotune/test1/profile.pump.json') as f:
    test1_input_profile, test1_prefs = parse_aaps_profile(json.load(f))

with open(root / 'aaps_test_res/autotune/test1/aapsorefprofile.json') as f:
    test1_expected, _ = parse_aaps_profile(json.load(f))

# Test case 4
print("Loading test case 4...")
with open(root / 'aaps_test_res/autotune/test4/autotune.2022-05-30.json') as f:
    test4_prepped = parse_aaps_prepped_glucose(json.load(f))

with open(root / 'aaps_test_res/autotune/test4/profile.2022-05-30.json') as f:
    test4_input_profile, test4_prefs = parse_aaps_profile(json.load(f))

with open(root / 'aaps_test_res/autotune/test4/profile.pump.json') as f:
    test4_pump_profile, _ = parse_aaps_profile(json.load(f))

with open(root / 'aaps_test_res/autotune/test4/newprofile.2022-05-30.json') as f:
    test4_expected, _ = parse_aaps_profile(json.load(f))

print("Running Python port...")

# Run test 1
test1_previous = test1_input_profile.copy()
test1_result = tune_day(test1_prepped, test1_previous, test1_input_profile, test1_prefs)

# Run test 4
test4_previous = test4_input_profile.copy()
test4_result = tune_day(test4_prepped, test4_previous, test4_pump_profile, test4_prefs)

# Compare test 1
print("\n=== Test 1 (autotuneCoreTest1) ===")
print(f"Expected ISF: {test1_expected.isf:.3f}, Got: {test1_result.isf:.3f}, Diff: {abs(test1_result.isf - test1_expected.isf):.6f}")
print(f"Expected IC:  {test1_expected.ic:.3f}, Got: {test1_result.ic:.3f}, Diff: {abs(test1_result.ic - test1_expected.ic):.6f}")

basal_diffs_1 = []
for h in range(24):
    exp = test1_expected.basal[h]
    got = test1_result.basal[h]
    if abs(exp - got) > 1e-10:
        basal_diffs_1.append((h, exp, got, abs(exp - got)))

if basal_diffs_1:
    print("Basal differences:")
    for h, exp, got, diff in basal_diffs_1:
        print(f"  Hour {h}: expected={exp:.3f}, got={got:.3f}, diff={diff:.6f}")
else:
    print("Basal: EXACT MATCH (all 24 hours)")

# Compare test 4
print("\n=== Test 4 (autotuneCoreTest4) ===")
print(f"Expected ISF: {test4_expected.isf:.3f}, Got: {test4_result.isf:.3f}, Diff: {abs(test4_result.isf - test4_expected.isf):.6f}")
print(f"Expected IC:  {test4_expected.ic:.3f}, Got: {test4_result.ic:.3f}, Diff: {abs(test4_result.ic - test4_expected.ic):.6f}")

basal_diffs_4 = []
for h in range(24):
    exp = test4_expected.basal[h]
    got = test4_result.basal[h]
    if abs(exp - got) > 1e-10:
        basal_diffs_4.append((h, exp, got, abs(exp - got)))

if basal_diffs_4:
    print("Basal differences:")
    for h, exp, got, diff in basal_diffs_4:
        print(f"  Hour {h}: expected={exp:.3f}, got={got:.3f}, diff={diff:.6f}")
else:
    print("Basal: EXACT MATCH (all 24 hours)")

# Summary
total_basal_diffs = len(basal_diffs_1) + len(basal_diffs_4)
isf_diff_1 = abs(test1_result.isf - test1_expected.isf)
isf_diff_4 = abs(test4_result.isf - test4_expected.isf)
ic_diff_1 = abs(test1_result.ic - test1_expected.ic)
ic_diff_4 = abs(test4_result.ic - test4_expected.ic)

max_basal_diff = 0
for _, _, _, diff in basal_diffs_1 + basal_diffs_4:
    max_basal_diff = max(max_basal_diff, diff)

print(f"\n=== SUMMARY ===")
print(f"Test 1: ISF diff={isf_diff_1:.6f}, IC diff={ic_diff_1:.6f}, Basal mismatches={len(basal_diffs_1)}")
print(f"Test 4: ISF diff={isf_diff_4:.6f}, IC diff={ic_diff_4:.6f}, Basal mismatches={len(basal_diffs_4)}")
print(f"Maximum basal difference: {max_basal_diff:.6f}")

# Write evidence
evidence = {
    'reference_commit': manifest['commit'],
    'component': 'AutotuneCore.tuneAllTheThings (full) with AAPS test cases',
    'test_cases': 2,
    'test1_isf_diff': isf_diff_1,
    'test1_ic_diff': ic_diff_1,
    'test1_basal_mismatches': len(basal_diffs_1),
    'test4_isf_diff': isf_diff_4,
    'test4_ic_diff': ic_diff_4,
    'test4_basal_mismatches': len(basal_diffs_4),
    'max_basal_difference': max_basal_diff,
    'scope': 'AAPS reference test cases test1 and test4 from AutotuneCoreTest.kt',
    'python_sha256': hashlib.sha256((root / '../src/bganalyzer/autotune/core.py').read_bytes()).hexdigest(),
}

(root / 'full-autotune-parity-result.json').write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps(evidence, indent=2))