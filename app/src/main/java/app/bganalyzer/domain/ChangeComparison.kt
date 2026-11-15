package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset

/** Glucose over one stretch of time. [days] is the stretch length, [readings] how many readings fell in it. */
data class PeriodSummary(val days: Double, val readings: Int, val timeInRange: TimeInRange) {
    /** Enough readings to compare: at least two days' worth at one reading per 5 minutes, 60% present. */
    val enough get() = days >= ChangeComparison.MIN_DAYS && readings >= days * 288 * 0.6
}

/** How glucose looked before and after one profile change. */
data class ChangeResult(
    val change: EffectiveProfile,
    val before: PeriodSummary,
    val after: PeriodSummary,
    /** Total basal per day before and after, from the profile schedules (null if the earlier profile is unknown). */
    val basalPerDayBefore: Double?,
    val basalPerDayAfter: Double,
)

/**
 * Compares glucose in the days before and after each profile change. Each window stops at the neighbouring change,
 * so a result never mixes two settings. It shows what happened, not why: other things change too.
 */
object ChangeComparison {
    const val WINDOW_DAYS = 7
    const val MIN_DAYS = 2.0
    internal const val DAY_MS = 86_400_000L

    /**
     * [readings] sorted by time and already stripped of excluded days. [changes] are all known switches, oldest first.
     * Only the last steady switch of each local day counts (several edits in one day are one change), and a day that ends
     * on the same settings as the day before is not a change at all.
     */
    fun compare(readings: List<GlucoseReadingEntity>, changes: List<EffectiveProfile>, periodFromMs: Long, nowMs: Long, zone: ZoneId = ZoneOffset.UTC): List<ChangeResult> {
        val perDay = changes.filter { !it.isTemporary }.sortedBy { it.startMs }
            .groupBy { LocalDate.ofInstant(Instant.ofEpochMilli(it.startMs), zone) }.values.map { it.last() }.sortedBy { it.startMs }
        val sorted = perDay.filterIndexed { i, c -> i == 0 || !ProfileChanges.sameSettings(perDay[i - 1], c) }
        return sorted.mapIndexedNotNull { i, c ->
            if (c.startMs < periodFromMs) return@mapIndexedNotNull null
            val prev = sorted.getOrNull(i - 1)
            val next = sorted.getOrNull(i + 1)
            val beforeFrom = maxOf(c.startMs - WINDOW_DAYS * DAY_MS, prev?.startMs ?: Long.MIN_VALUE)
            val afterTo = minOf(c.startMs + WINDOW_DAYS * DAY_MS, next?.startMs ?: Long.MAX_VALUE, nowMs)
            ChangeResult(
                c, summary(readings, beforeFrom, c.startMs), summary(readings, c.startMs, afterTo),
                prev?.let { totalBasal(it.basal) }, totalBasal(c.basal),
            )
        }
    }

    internal fun summary(readings: List<GlucoseReadingEntity>, from: Long, to: Long): PeriodSummary {
        val inside = readings.filter { it.timestampMs in from until to }
        return PeriodSummary(maxOf(0L, to - from) / DAY_MS.toDouble(), inside.size, TimeInRange.of(inside.map { it.mgdl }))
    }

    /** Units per day of a basal schedule. */
    fun totalBasal(steps: List<BasalStep>): Double {
        if (steps.isEmpty()) return 0.0
        val sorted = steps.sortedBy { it.secondsFromMidnight }
        var total = 0.0
        for ((i, s) in sorted.withIndex()) {
            val end = sorted.getOrNull(i + 1)?.secondsFromMidnight ?: 86_400
            total += s.rateUph * (end - s.secondsFromMidnight) / 3600.0
        }
        // Time before the first step belongs to the last step (the schedule wraps).
        sorted.first().secondsFromMidnight.takeIf { it > 0 }?.let { total += sorted.last().rateUph * it / 3600.0 }
        return total
    }
}
