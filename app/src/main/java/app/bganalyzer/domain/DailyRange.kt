package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/** One local day of glucose: time in range and how many readings it has. */
data class DayStat(val date: LocalDate, val timeInRange: TimeInRange, val readings: Int) {
    /** A day with under a third of its readings says little, so it is drawn faded. */
    val complete get() = readings >= MIN_READINGS

    companion object { const val MIN_READINGS = 96 }
}

object DailyRange {
    /** Every local day from [fromMs] to [toMs] (oldest first), including days with no readings. [points] need not be sorted. */
    fun of(points: List<GlucoseReadingEntity>, zone: ZoneId, fromMs: Long, toMs: Long): List<DayStat> {
        val byDay = points.groupBy { LocalDate.ofInstant(Instant.ofEpochMilli(it.timestampMs), zone) }
        val first = LocalDate.ofInstant(Instant.ofEpochMilli(fromMs), zone)
        val last = LocalDate.ofInstant(Instant.ofEpochMilli(toMs - 1), zone)
        return generateSequence(first) { it.plusDays(1) }.takeWhile { !it.isAfter(last) }.map { d ->
            val rows = byDay[d].orEmpty()
            DayStat(d, TimeInRange.of(rows.map { it.mgdl }), rows.size)
        }.toList()
    }
}
