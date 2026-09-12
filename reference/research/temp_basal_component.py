# SPDX-License-Identifier: AGPL-3.0-only
# Research translation of pinned AAPS AutotuneIob.convertToBoluses(TB,...).
# See ../aaps/LICENSE.txt and manifest.json. Not used by the application.
import math
from decimal import Decimal


def temp_basal_contributions(timestamp_ms, duration_ms, rate, is_absolute, historical_basal, comparison_basal):
    """Convert one already-resolved segment to (timestamp, signed units) pairs.

    Internal percentage rate is total percent (100 = neutral), not the serialized
    Nightscout percent offset. Profile resolution, splitting and actual delivery
    confirmation are caller responsibilities, outside this component.
    """
    if type(timestamp_ms) is not int or timestamp_ms < 0 or type(duration_ms) is not int or duration_ms < 0:
        raise ValueError("Explicit nonnegative integer timestamps/durations required")
    if type(is_absolute) is not bool:
        raise ValueError("Explicit absolute/percentage semantics required")
    for value in (rate, historical_basal, comparison_basal):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("Explicit finite nonnegative rates required")
    minutes = duration_ms // 60_000
    if minutes == 0:
        return []
    net = rate - comparison_basal if is_absolute else rate / 100.0 * historical_basal - comparison_basal
    net = float(Decimal(math.floor(net / 0.001 + 0.5)) * Decimal("0.001")) if net else 0.0
    count = math.ceil(minutes / 5.0)
    spacing = minutes / float(count)
    return [(int(timestamp_ms + j * spacing * 60 * 1000 + 0.5 * spacing * 60 * 1000), net * spacing / 60.0) for j in range(count)]
