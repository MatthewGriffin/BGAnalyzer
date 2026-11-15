package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.TreatmentEntity
import java.time.Instant
import java.time.ZoneId

/**
 * How glucose moved on its own in one time of day, on days with no carbs or manual bolus in the block or the
 * [FastingDrift.QUIET_BEFORE_MS] before it. Needs no loop data, so it works for users without a closed loop.
 */
data class DriftBlockStats(
    val startHour: Int,
    val endHour: Int,
    /** Quiet days with enough readings. */
    val days: Int,
    /** Middle value of the per-day slope, mg/dL per hour. Positive means glucose rose. */
    val medianSlopeMgdlPerHour: Double,
    val risingDays: Int,
    val fallingDays: Int,
) {
    val enoughDays get() = days >= TimeBlocks.MIN_DAYS
}

object FastingDrift {
    const val QUIET_BEFORE_MS = 4 * 3_600_000L
    /** A day's slope counts as a rise or a fall only beyond this many mg/dL per hour. */
    const val FLAT_BAND = 5.0
    private const val MIN_COVERAGE = 0.6
    /** Quiet windows that start or contain a low are skipped: they are likely hypo treatment or an unlogged event. */
    private const val LOW_MGDL = 70.0

    /** Carbs and manual boluses (not SMBs, which the loop gives on its own) break a quiet window. */
    fun events(treatments: List<TreatmentEntity>): List<Long> =
        treatments.filter { it.valid && ((it.carbs ?: 0.0) > 0 || ((it.insulin ?: 0.0) > 0 && !it.isSmb)) }.map { it.timestampMs }.sorted()

    /**
     * [insulinDays] are the local dates that have insulin records ([DayQuality.daysWithInsulin]); a block on any other date is
     * skipped, because a day with no insulin records is a pump or logging failure, not a quiet day. Null skips that check.
     */
    fun analyze(readings: List<GlucoseReadingEntity>, treatments: List<TreatmentEntity>, zone: ZoneId, blockHours: Int, insulinDays: Set<String>? = null): List<DriftBlockStats> {
        require(blockHours in TimeBlocks.ALLOWED_BLOCK_HOURS)
        val ev = events(treatments)
        val cells = HashMap<Pair<java.time.LocalDate, Int>, MutableList<GlucoseReadingEntity>>()
        for (r in readings) {
            val l = Instant.ofEpochMilli(r.timestampMs).atZone(zone)
            cells.getOrPut(l.toLocalDate() to l.hour / blockHours) { ArrayList() }.add(r)
        }
        val slopes = HashMap<Int, MutableList<Double>>()
        for ((key, list) in cells) {
            if (list.size < blockHours * 12 * MIN_COVERAGE) continue
            if (insulinDays != null && key.first.toString() !in insulinDays) continue
            val first = list.minOf { it.timestampMs }; val last = list.maxOf { it.timestampMs }
            if (ev.any { it in (first - QUIET_BEFORE_MS)..last }) continue
            if (list.any { it.mgdl < LOW_MGDL }) continue
            slopes.getOrPut(key.second) { ArrayList() }.add(slope(list))
        }
        return (0 until 24 / blockHours).map { b ->
            val s = slopes[b].orEmpty().sorted()
            DriftBlockStats(
                b * blockHours, (b + 1) * blockHours, s.size,
                if (s.isEmpty()) 0.0 else if (s.size % 2 == 1) s[s.size / 2] else (s[s.size / 2 - 1] + s[s.size / 2]) / 2,
                s.count { it > FLAT_BAND }, s.count { it < -FLAT_BAND },
            )
        }
    }

    /** Least-squares slope in mg/dL per hour. */
    private fun slope(list: List<GlucoseReadingEntity>): Double {
        val t0 = list.minOf { it.timestampMs }
        val xs = list.map { (it.timestampMs - t0) / 3_600_000.0 }
        val mx = xs.average(); val my = list.map { it.mgdl }.average()
        val den = xs.sumOf { (it - mx) * (it - mx) }
        if (den == 0.0) return 0.0
        return xs.indices.sumOf { (xs[it] - mx) * (list[it].mgdl - my) } / den
    }
}
