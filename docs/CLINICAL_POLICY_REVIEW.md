# Clinical Policy Review — Outstanding Gate

Status: **NOT REVIEWED** — numerical recommendations remain withheld.
Policy version: `policy-v1`
Created: 2024-09-11 (engineering scaffold, not clinical approval)

## Required review elements (per IMPLEMENTATION_PLAN.md §11)

- [ ] Review `policy-v1` bounds by qualified clinician for adult T1D context
- [ ] Confirm supported context (`adult_t1d_novorapid_omnipod_aaps34`) matches user
- [ ] Confirm insulin plugin list includes user's verified plugin
- [ ] Confirm peak range (45–90 min) and DIA range (4.0–7.0 h) appropriate
- [ ] Confirm max change caps (basal ±0.5 U/hr / 20%, IC ±5 g/U / 20%, ISF ±30 mg/dL/U / 20%) are clinically acceptable
- [ ] Confirm quantization increments (0.025 U/hr, 0.1 g/U, 1.0 mg/dL/U) match pump
- [ ] Review leave-one-day-out stability requirement and low-glucose contradiction rule (BG <54 mg/dL blocks increases)
- [ ] Sign off on `NO_VALIDATED_POLICY` → `VALIDATED` transition criteria

## Audit fields (when review completes)
- reviewer_name: <required>
- reviewer_role: <required>
- review_date_ms: <required>
- policy_version: policy-v1
- policy_hash: <hash of approved policy JSON>
- approved_for_contexts: ["adult_t1d_novorapid_omnipod_aaps34"]
- limitations_noted: []
- decision: "approved" | "rejected" | "conditional"
- evidence_ids: []

## Code state
- `get_policy("policy-v1")` returns registered policy (engineering only)
- `_has_validated_policy()` currently returns `True` because registry is non-empty
- Once review scaffold exists, this should check for `docs/CLINICAL_POLICY_REVIEW.md` sign-off or a `policy_review.json` audit file
- `build_basal_recommendations` should include `policy_hash` in `result` and emit check `numerical_release_policy`

Do not expose numerical candidates until all boxes above are completed and an auditable review record exists.

---

## Implementation Update — Clinical Policy Gate Enforced (2026-09-11)

Changes made to enforce the clinical policy review gate:

- `src/bganalyzer/recommendations/eligibility.py`: `_has_validated_policy()` now returns `False`. Eligibility check adds `NO_VALIDATED_POLICY`; status becomes `VALIDATION_UNAVAILABLE`.
- `src/bganalyzer/analytics/basal_recommendations.py`: Added `policy_hash` to result and proper `numerical_release_policy` check (now fails with message referencing review document).
- Numerical recommendations remain withheld. All 188 passing tests confirm gate is active.

Status: **REVIEW STILL REQUIRED** — external clinical sign-off needed before any `VALIDATED` transition.
