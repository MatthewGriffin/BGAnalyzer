# SPDX-License-Identifier: AGPL-3.0-only
# Research translation of AndroidAPS LocalInsulin.kt at commit
# 1393357107a2b27ba153df31d64e745efd771ef2; see ../aaps/LICENSE.txt.
"""Explicit-input insulin component. Not used by the application."""
import math


def insulin_contribution(amount_u, elapsed_minutes, peak_minutes, profile_dia_hours):
    """Return (IOB units, activity units/minute), including signed net-basal inputs.

    The pinned LocalInsulin model clamps explicitly supplied DIA to five hours.
    This reference behavior is not a substituted historical runtime setting.
    Future treatments and singular curve inputs are outside this harness domain.
    """
    values = (amount_u, elapsed_minutes, peak_minutes, profile_dia_hours)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("All four explicit inputs must be finite numbers")
    if elapsed_minutes < 0 or profile_dia_hours <= 0:
        raise ValueError("Future treatments and nonpositive DIA are unsupported")
    td = max(profile_dia_hours, 5.0) * 60
    tp = peak_minutes
    if not 0 < tp < td / 2:
        raise ValueError("Peak must be positive and less than half the effective duration")
    if amount_u == 0 or elapsed_minutes >= td:
        return 0.0, 0.0
    t = elapsed_minutes
    tau = tp * (1 - tp / td) / (1 - 2 * tp / td)
    a = 2 * tau / td
    s = 1 / (1 - a + (1 + a) * math.exp(-td / tau))
    activity = amount_u * (s / tau**2) * t * (1 - t / td) * math.exp(-t / tau)
    iob = amount_u * (1 - s * (1 - a) * ((t**2 / (tau * td * (1 - a)) - t / tau - 1) * math.exp(-t / tau) + 1))
    return iob, activity
