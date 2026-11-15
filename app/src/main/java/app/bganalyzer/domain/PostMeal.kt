package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.TreatmentEntity
import java.time.ZoneId

/** Carbs eaten at one time. Carb entries close together are merged into one meal. */
data class Meal(val timeMs: Long, val carbs: Double)

/** What glucose did after the meals that started in one time-of-day block. */
data class MealBlockStats(
    val startHour: Int,
    val endHour: Int,
    /** Meals that had enough readings around them to measure. */
    val meals: Int,
    /** Middle value of (highest glucose within 3 h) minus (glucose at the meal), in mg/dL. */
    val medianRiseMgdl: Double,
    /** Middle value of glucose 2 h after the meal, in mg/dL. Null when no meal had a reading near the 2 h mark. */
    val medianAt2hMgdl: Double?,
    /** Meals whose glucose was above the high limit 2 h later (only counted for meals that had a 2 h reading). */
    val highAt2h: Int,
    val withReading2h: Int,
    /** Meals followed by a reading below the low limit within 4 h. */
    val lowWithin4h: Int,
) {
    val enoughMeals get() = meals >= PostMeal.MIN_MEALS
}

object PostMeal {
    const val MIN_MEALS = 5
    private const val MERGE_WINDOW_MS = 30 * 60_000L
    private const val BASELINE_LOOKBACK_MS = 15 * 60_000L
    private const val PEAK_WINDOW_MS = 3 * 3_600_000L
    private const val LOW_WINDOW_MS = 4 * 3_600_000L
    private const val AT_2H_MS = 2 * 3_600_000L
    private const val AT_2H_TOLERANCE_MS = 10 * 60_000L
    /** Fewer carbs than this are treated as low treatment or noise, not a meal. */
    const val MIN_MEAL_CARBS = 5.0
    /** Need this share of the 3 h window's readings (one per 5 minutes) to measure a meal. */
    private const val MIN_WINDOW_COVERAGE = 0.6

    /** Valid treatments with carbs, with entries within 30 minutes merged. Carbs sit on bolus records as well as carb records. */
    fun meals(treatments: List<TreatmentEntity>): List<Meal> {
        val merged = ArrayList<Meal>()
        for (t in treatments.filter { it.valid && (it.carbs ?: 0.0) > 0 }.sortedBy { it.timestampMs }) {
            val last = merged.lastOrNull()
            if (last != null && t.timestampMs - last.timeMs <= MERGE_WINDOW_MS) {
                merged[merged.size - 1] = last.copy(carbs = last.carbs + t.carbs!!)
            } else merged.add(Meal(t.timestampMs, t.carbs!!))
        }
        return merged.filter { it.carbs >= MIN_MEAL_CARBS }
    }

    /** [readings] must be sorted by time. Meals eaten while glucose was already low are skipped: they are hypo treatments. */
    fun analyze(
        readings: List<GlucoseReadingEntity>,
        meals: List<Meal>,
        zone: ZoneId,
        blockHours: Int,
        ranges: GlucoseRanges = GlucoseRanges(),
    ): List<MealBlockStats> {
        require(blockHours in TimeBlocks.ALLOWED_BLOCK_HOURS)
        val times = LongArray(readings.size) { readings[it].timestampMs }
        val perBlock = HashMap<Int, MutableList<Measured>>()
        for (m in meals) {
            measure(readings, times, m, ranges)?.let {
                perBlock.getOrPut(TimeBlocks.localHour(m.timeMs, zone) / blockHours) { ArrayList() }.add(it)
            }
        }
        return (0 until 24 / blockHours).map { b ->
            val list = perBlock[b].orEmpty()
            val at2h = list.mapNotNull { it.at2h }
            MealBlockStats(
                startHour = b * blockHours,
                endHour = (b + 1) * blockHours,
                meals = list.size,
                medianRiseMgdl = median(list.map { it.rise }) ?: 0.0,
                medianAt2hMgdl = median(at2h),
                highAt2h = at2h.count { it > ranges.highAbove },
                withReading2h = at2h.size,
                lowWithin4h = list.count { it.lowWithin4h },
            )
        }
    }

    private class Measured(val rise: Double, val at2h: Double?, val lowWithin4h: Boolean)

    private fun measure(readings: List<GlucoseReadingEntity>, times: LongArray, meal: Meal, ranges: GlucoseRanges): Measured? {
        val start = firstIndexAtOrAfter(times, meal.timeMs - BASELINE_LOOKBACK_MS)
        // Baseline: the last reading at or before the meal, within 15 minutes.
        var i = firstIndexAtOrAfter(times, meal.timeMs + 1) - 1
        if (i < start || i < 0) return null
        val baseline = readings[i].mgdl
        if (baseline < ranges.lowBelow) return null
        val from = i + 1
        val peakEnd = firstIndexAtOrAfter(times, meal.timeMs + PEAK_WINDOW_MS + 1)
        if (peakEnd - from < PEAK_WINDOW_MS / 300_000 * MIN_WINDOW_COVERAGE) return null
        val peak = (from until peakEnd).maxOf { readings[it].mgdl }
        val at2hTarget = meal.timeMs + AT_2H_MS
        val at2h = (from until peakEnd).map { readings[it] }
            .filter { kotlin.math.abs(it.timestampMs - at2hTarget) <= AT_2H_TOLERANCE_MS }
            .minByOrNull { kotlin.math.abs(it.timestampMs - at2hTarget) }?.mgdl
        val lowEnd = firstIndexAtOrAfter(times, meal.timeMs + LOW_WINDOW_MS + 1)
        val low = (from until lowEnd).any { readings[it].mgdl < ranges.lowBelow }
        return Measured(peak - baseline, at2h, low)
    }

    private fun firstIndexAtOrAfter(times: LongArray, t: Long): Int {
        var lo = 0; var hi = times.size
        while (lo < hi) { val mid = (lo + hi) ushr 1; if (times[mid] < t) lo = mid + 1 else hi = mid }
        return lo
    }

    private fun median(values: List<Double>): Double? {
        if (values.isEmpty()) return null
        val s = values.sorted()
        return if (s.size % 2 == 1) s[s.size / 2] else (s[s.size / 2 - 1] + s[s.size / 2]) / 2
    }
}
