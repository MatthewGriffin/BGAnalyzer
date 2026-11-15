package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.TreatmentEntity
import java.time.Instant
import java.time.ZoneId

/** Leaves days the user marked as bad (pump failure, pens in use) out of an analysis. Pure code. */
object ExcludedDays {
    fun isExcluded(timeMs: Long, zone: ZoneId, dates: Set<String>) =
        dates.isNotEmpty() && Instant.ofEpochMilli(timeMs).atZone(zone).toLocalDate().toString() in dates

    fun readings(list: List<GlucoseReadingEntity>, zone: ZoneId, dates: Set<String>) =
        if (dates.isEmpty()) list else list.filterNot { isExcluded(it.timestampMs, zone, dates) }

    fun treatments(list: List<TreatmentEntity>, zone: ZoneId, dates: Set<String>) =
        if (dates.isEmpty()) list else list.filterNot { isExcluded(it.timestampMs, zone, dates) }
}
