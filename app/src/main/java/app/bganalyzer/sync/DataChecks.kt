package app.bganalyzer.sync

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/** Consecutive days ([from] to [to] inclusive) on which a source has too few records although it was asked for. */
data class EmptyRange(val source: String, val from: LocalDate, val to: LocalDate) {
    val days get() = (to.toEpochDay() - from.toEpochDay() + 1).toInt()
}

object DataChecks {
    /**
     * Days of [period] that were fully requested from Nightscout (inside [covered]) yet have fewer than [minPerDay]
     * records in [timestamps]. These are days Nightscout itself has nothing for, as far as the app can tell. Today and
     * the day before are left out because the data may still be arriving. Consecutive days are merged.
     */
    fun emptyRanges(
        source: String,
        timestamps: List<Long>,
        covered: List<Span>,
        period: Span,
        zone: ZoneId,
        minPerDay: Int,
        nowMs: Long,
    ): List<EmptyRange> {
        val perDay = timestamps.groupingBy { Instant.ofEpochMilli(it).atZone(zone).toLocalDate() }.eachCount()
        val last = Instant.ofEpochMilli(nowMs).atZone(zone).toLocalDate().minusDays(1)
        var day = Instant.ofEpochMilli(period.startMs).atZone(zone).toLocalDate().plusDays(1)   // the first day is only partly in the period
        val out = ArrayList<EmptyRange>()
        while (day < last) {
            val span = Span(day.atStartOfDay(zone).toInstant().toEpochMilli(), day.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli())
            if (Intervals.subtract(span, covered).isEmpty() && (perDay[day] ?: 0) < minPerDay) {
                val prev = out.lastOrNull()
                if (prev != null && prev.to.plusDays(1) == day) out[out.size - 1] = prev.copy(to = day) else out.add(EmptyRange(source, day, day))
            }
            day = day.plusDays(1)
        }
        return out
    }
}
