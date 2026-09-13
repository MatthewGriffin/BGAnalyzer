"""Numerical release policy - versioned, tested policy for candidate generation.

Implements section 11 of IMPLEMENTATION_PLAN.md - this is an explicit engineering
selection rule, NOT a validated medical safety guarantee.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
from decimal import Decimal


@dataclass
class PolicyBounds:
    """Bounds for a single parameter family."""

    # Maximum absolute change from baseline (units depend on family)
    max_absolute_change: float

    # Maximum percentage change from baseline
    max_percent_change: float

    # Minimum value allowed
    min_value: float

    # Maximum value allowed
    max_value: float

    # Entry increment (quantization step)
    entry_increment: float


@dataclass
class NumericalReleasePolicy:
    """Complete numerical release policy for a specific context.

    This policy defines the allowable bounds for basal, IC, and ISF changes.
    It is versioned and must be reviewed before enabling numerical output.
    """

    version: str
    description: str
    created_ms: int

    # Supported contexts (e.g., "adult_t1d_novorapid_omnipod_aaps34")
    supported_contexts: list[str] = field(default_factory=list)

    # Per-family bounds
    basal_bounds: PolicyBounds = field(default_factory=lambda: PolicyBounds(
        max_absolute_change=0.5,      # U/hr
        max_percent_change=0.20,      # 20%
        min_value=0.0,
        max_value=10.0,
        entry_increment=0.025,        # AAPS pump increment
    ))

    ic_bounds: PolicyBounds = field(default_factory=lambda: PolicyBounds(
        max_absolute_change=5.0,      # g/U
        max_percent_change=0.20,      # 20%
        min_value=1.0,
        max_value=100.0,
        entry_increment=0.1,
    ))

    isf_bounds: PolicyBounds = field(default_factory=lambda: PolicyBounds(
        max_absolute_change=30.0,     # mg/dL/U
        max_percent_change=0.20,      # 20%
        min_value=10.0,
        max_value=200.0,
        entry_increment=1.0,
    ))

    # General constraints
    min_eligible_days: int = 7
    min_cgm_coverage_pct: float = 90.0
    max_cgm_gap_minutes: int = 20
    low_glucose_threshold_mgdl: int = 54

    # Supported insulin configurations
    supported_insulin_plugins: list[str] = field(default_factory=lambda: [
        "rapid-acting", "ultra-rapid",
        "OREF_RAPID_ACTING", "OREF_ULTRA_RAPID_ACTING", "OREF_FREE_PEAK", "OREF_LYUMJEV",
    ])
    supported_peak_range: tuple[int, int] = (45, 90)
    supported_dia_range: tuple[float, float] = (4.0, 7.0)

    # Pump constraints
    pump_entry_increments: Dict[str, float] = field(default_factory=lambda: {
        "basal": 0.025,
        "ic": 0.1,
        "isf": 1.0,
    })

    def validate_context(self, context: str, insulin_plugin: str, peak_minutes: int, dia_hours: float) -> tuple[bool, str]:
        """Validate if the current context is supported by this policy."""
        if context not in self.supported_contexts:
            return False, f"Context '{context}' not in supported contexts: {self.supported_contexts}"

        if insulin_plugin not in self.supported_insulin_plugins:
            return False, f"Insulin plugin '{insulin_plugin}' not supported: {self.supported_insulin_plugins}"

        if not (self.supported_peak_range[0] <= peak_minutes <= self.supported_peak_range[1]):
            return False, f"Peak {peak_minutes}min outside supported range {self.supported_peak_range}"

        if not (self.supported_dia_range[0] <= dia_hours <= self.supported_dia_range[1]):
            return False, f"DIA {dia_hours}h outside supported range {self.supported_dia_range}"

        return True, "OK"

    def validate_basal_change(self, baseline: float, proposed: float) -> tuple[bool, str]:
        """Validate a single basal rate change."""
        if proposed < self.basal_bounds.min_value:
            return False, f"Basal {proposed} below minimum {self.basal_bounds.min_value}"
        if proposed > self.basal_bounds.max_value:
            return False, f"Basal {proposed} above maximum {self.basal_bounds.max_value}"

        abs_change = abs(proposed - baseline)
        if abs_change > self.basal_bounds.max_absolute_change:
            return False, f"Basal change {abs_change:.3f} exceeds max {self.basal_bounds.max_absolute_change}"

        if baseline > 0:
            pct_change = abs_change / baseline
            if pct_change > self.basal_bounds.max_percent_change:
                return False, f"Basal change {pct_change:.1%} exceeds max {self.basal_bounds.max_percent_change:.0%}"

        return True, "OK"

    def validate_ic_change(self, baseline: float, proposed: float) -> tuple[bool, str]:
        """Validate an IC (carb ratio) change."""
        if proposed < self.ic_bounds.min_value:
            return False, f"IC {proposed} below minimum {self.ic_bounds.min_value}"
        if proposed > self.ic_bounds.max_value:
            return False, f"IC {proposed} above maximum {self.ic_bounds.max_value}"

        abs_change = abs(proposed - baseline)
        if abs_change > self.ic_bounds.max_absolute_change:
            return False, f"IC change {abs_change:.1f} exceeds max {self.ic_bounds.max_absolute_change}"

        if baseline > 0:
            pct_change = abs_change / baseline
            if pct_change > self.ic_bounds.max_percent_change:
                return False, f"IC change {pct_change:.1%} exceeds max {self.ic_bounds.max_percent_change:.0%}"

        return True, "OK"

    def validate_isf_change(self, baseline: float, proposed: float) -> tuple[bool, str]:
        """Validate an ISF change."""
        if proposed < self.isf_bounds.min_value:
            return False, f"ISF {proposed} below minimum {self.isf_bounds.min_value}"
        if proposed > self.isf_bounds.max_value:
            return False, f"ISF {proposed} above maximum {self.isf_bounds.max_value}"

        abs_change = abs(proposed - baseline)
        if abs_change > self.isf_bounds.max_absolute_change:
            return False, f"ISF change {abs_change:.1f} exceeds max {self.isf_bounds.max_absolute_change}"

        if baseline > 0:
            pct_change = abs_change / baseline
            if pct_change > self.isf_bounds.max_percent_change:
                return False, f"ISF change {pct_change:.1%} exceeds max {self.isf_bounds.max_percent_change:.0%}"

        return True, "OK"

    def quantize_basal(self, value: float) -> float:
        """Quantize basal rate to the pump's entry precision.

        AAPS on Android/Omnipod accepts basal rates to two decimal places
        (e.g. 1.35, 1.40 U/hr). The 0.025 step used to be applied here, which
        produced three-decimal values such as 1.325 that the pump rejects on
        entry. Two-decimal rounding is applied after any pump-increment step so
        the result is always enterable.
        """
        inc = self.pump_entry_increments.get("basal", 0.025)
        stepped = round(value / inc) * inc
        return round(stepped, 2)

    def quantize_ic(self, value: float) -> float:
        """Quantize IC to pump entry increment."""
        inc = self.pump_entry_increments.get("ic", 0.1)
        return round(value / inc) * inc

    def quantize_isf(self, value: float) -> float:
        """Quantize ISF to pump entry increment."""
        inc = self.pump_entry_increments.get("isf", 1.0)
        return round(value / inc) * inc


# Default policy v1 - engineering selection rules, NOT medical validation
DEFAULT_POLICY_V1 = NumericalReleasePolicy(
    version="policy-v1",
    description="Initial engineering policy for adult T1D with NovoRapid on Omnipod via AAPS 3.4+",
    created_ms=1726000000000,  # 2024-09-11 approx
    supported_contexts=["adult_t1d_novorapid_omnipod_aaps34"],
)

# Policy registry
_policy_registry: Dict[str, NumericalReleasePolicy] = {
    "policy-v1": DEFAULT_POLICY_V1,
}


def get_policy(version: str = "policy-v1") -> Optional[NumericalReleasePolicy]:
    """Get policy by version."""
    return _policy_registry.get(version)


def register_policy(policy: NumericalReleasePolicy) -> None:
    """Register a new policy version."""
    _policy_registry[policy.version] = policy


def list_policies() -> list[str]:
    """List available policy versions."""
    return list(_policy_registry.keys())

def policy_fingerprint(policy):
    """Bind a release audit to the exact policy, including every nested bound."""
    import hashlib
    import json
    from dataclasses import asdict
    return hashlib.sha256(json.dumps(asdict(policy), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validated_policy_audit(policy, path="policy_review.json"):
    """Validate audit integrity; a claimed approval with an unrelated hash fails.

    This checks technical provenance only, not a reviewer's clinical credentials.
    Evidence hashes must cover every referenced file, with no missing files.
    """
    import hashlib
    import json
    from pathlib import Path
    try:
        audit = json.loads(Path(path).read_text())
        if (audit.get("status") != "APPROVED" or audit.get("decision") != "approved"
                or audit.get("policy_version") != policy.version
                or audit.get("policy_hash") != policy_fingerprint(policy)):
            return False
        ids = audit.get("evidence_ids")
        hashes = audit.get("evidence_hashes")
        if not isinstance(ids, list) or not ids or not isinstance(hashes, dict):
            return False
        root = Path(path).resolve().parent
        for name in ids:
            target = (root / name).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                return False
            if hashlib.sha256(target.read_bytes()).hexdigest() != hashes.get(name):
                return False
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False
