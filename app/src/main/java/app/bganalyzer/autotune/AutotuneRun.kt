// Ported from AndroidAPS 3.4.2.1 (commit 1393357107a2b27ba153df31d64e745efd771ef2), autotune/AutotunePlugin.kt
// (the day-by-day loop). Copyright the AndroidAPS contributors, licensed under AGPL-3.0 (see LICENSE).
package app.bganalyzer.autotune

import app.bganalyzer.domain.BasalSegment
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime

/** A day autotune did not use, and why. [date] is the local date the 4 AM to 4 AM window starts on. */
data class SkippedDay(val date: String, val reason: String)

data class AutotuneResult(
    /** The profile before tuning (the starting point and the limit for every change). */
    val original: AtProfile,
    val tuned: AtProfile,
    val daysTuned: Int,
    val skipped: List<SkippedDay>,
    val log: List<String>,
)

/** Everything a run reads from the app's data. Pure lists and one lookup so the run can be tested without a database. */
class AutotuneData(
    val readings: List<AtReading>,
    /** Real boluses, including SMBs, as doses. */
    val boluses: List<Dose>,
    val meals: List<AtMeal>,
    /** Basal over a period, completely covered (temp basals plus scheduled basal), as `BasalTimeline.build` returns it. */
    val basalBetween: (fromMs: Long, toMs: Long) -> List<BasalSegment>,
)

object AutotuneRun {
    /** AAPS tunes each 24 hours from 4 AM to 4 AM so overnight basal is not cut in two. */
    const val START_HOUR = 4
    private const val HOUR_MS = 3_600_000L
    private const val DAY_MS = 24 * HOUR_MS

    /** The end of the last full 4 AM to 4 AM window before [nowMs]. */
    fun defaultEnd(nowMs: Long, zone: ZoneId): Long {
        val now = ZonedDateTime.ofInstant(java.time.Instant.ofEpochMilli(nowMs), zone)
        var end = now.toLocalDate().atTime(LocalTime.of(START_HOUR, 0)).atZone(zone)
        if (end.isAfter(now)) end = end.minusDays(1)
        return end.toInstant().toEpochMilli()
    }

    /**
     * Tunes [baseline] over the [daysBack] windows ending at [endMs], oldest first, each day starting from the profile the
     * previous day produced and bounded by [baseline] and [limits]. A day with no usable data, or for which [skipDate]
     * is true (excluded days), is skipped and reported, and the run carries on. [progress] gets (day, daysBack).
     */
    fun run(
        data: AutotuneData,
        baseline: AtProfile,
        limits: AutotuneLimits,
        zone: ZoneId,
        endMs: Long,
        daysBack: Int,
        options: PrepOptions = PrepOptions(),
        skipDate: (String) -> Boolean = { false },
        progress: (Int, Int) -> Unit = { _, _ -> },
    ): AutotuneResult {
        require(daysBack in 1..90) { "days back must be 1 to 90" }
        val log = AutotuneLog()
        val skipped = ArrayList<SkippedDay>()
        var tuned = baseline
        var used = 0
        val endLocal = ZonedDateTime.ofInstant(java.time.Instant.ofEpochMilli(endMs), zone)
        for (i in 0 until daysBack) {
            progress(i + 1, daysBack)
            val windowStart = endLocal.minusDays((daysBack - i).toLong())
            val windowEnd = windowStart.plusDays(1)
            val from = windowStart.toInstant().toEpochMilli()
            val to = windowEnd.toInstant().toEpochMilli()
            val date = windowStart.toLocalDate().toString()
            if (skipDate(date)) { skipped += SkippedDay(date, "marked as bad data"); continue }

            val lookback = (tuned.dia * HOUR_MS).toLong() + 2 * HOUR_MS
            val readings = data.readings.filter { it.timeMs in from..to }
            val boluses = data.boluses.filter { it.timeMs in (from - lookback)..to }
            if (readings.none { it.mgdl > 39 }) { skipped += SkippedDay(date, "no glucose readings"); continue }
            val doses = AutotuneDoses.build(boluses, data.basalBetween(from - lookback, to), tuned, zone)
            if (doses.isEmpty()) { skipped += SkippedDay(date, "no insulin data"); continue }
            val meals = data.meals.filter { it.timeMs in (from - lookback)..to }
            val prepped = AutotunePrep.categorize(PrepInput(readings, meals, doses), tuned, zone, limits.min5mCarbImpact, options, log)
            if (prepped == null) { skipped += SkippedDay(date, "not enough data to categorise"); continue }
            tuned = AutotuneCore.tune(prepped, tuned, baseline, limits, zone, log)
            used++
        }
        return AutotuneResult(baseline, tuned, used, skipped, log.lines)
    }
}
