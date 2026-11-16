package app.bganalyzer.autotune

import app.bganalyzer.domain.Confidence
import app.bganalyzer.domain.Swing
import app.bganalyzer.domain.SwingSum
import app.bganalyzer.domain.TimeInRange
import java.time.Instant
import java.time.ZoneId

/** What autotune found for one hour of the day, with this app's guard rails applied. */
data class HourAdvice(
    val hour: Int,
    val current: Double,
    /** What autotune ended with. */
    val tuned: Double,
    /** What the app suggests: [tuned], or [current] when a guard rail held an increase back. */
    val suggested: Double,
    val heldReason: String?,
    val confidence: Confidence,
    /** Average rate of change of glucose in this hour over the used days, mg/dL per hour (see [Swing]); null with too little data. */
    val swingMgdlPerHour: Double? = null,
    /** Glucose swings much more in this hour than in a typical hour, so its confidence was lowered one step. */
    val unsteady: Boolean = false,
)

data class AutotuneAdvice(
    val hours: List<HourAdvice>,
    val currentIsf: Double, val tunedIsf: Double,
    val currentCarbRatio: Double, val tunedCarbRatio: Double,
    val daysTuned: Int,
    val mealsUsed: Int = 0,
    val isfPoints: Int = 0,
    /** Over all used days: coefficient of variation (%) and average rate of change (mg/dL per hour). */
    val cvPct: Double? = null,
    val swingMgdlPerHour: Double? = null,
)

object AutotuneAdvisor {
    /** Pumps deliver basal in steps of 0.05 U/h (Omnipod), so suggested rates are rounded to it. */
    const val PUMP_STEP = 0.05

    fun roundToPumpStep(v: Double): Double = Math.round(v / PUMP_STEP) * PUMP_STEP

    /** Fewer meals than this over the run makes the carb ratio low confidence; fewer insulin-only readings does the same for the ISF. */
    const val MIN_MEALS = 10
    const val MIN_ISF_POINTS = 20

    /**
     * An hour counts as unsteady when its average rate of change is above [UNSTEADY_RATIO] times that of the median hour
     * and at least [UNSTEADY_FLOOR_MGDL_PER_H] (1 mmol/L per hour). Where glucose swings, positive and negative deviations cancel in
     * the average, so the suggestion there is less trustworthy: its confidence drops one step. It never blocks a suggestion.
     * A heuristic with no clinical standard behind it; on 14 real days it flagged 2 of 24 hours.
     */
    const val UNSTEADY_RATIO = 1.5
    const val UNSTEADY_FLOOR_MGDL_PER_H = 18.0
    private const val MIN_SWING_HOURS = 1.0

    /** Share of days with a low in an hour of day that stops a basal increase there. */
    const val LOW_DAY_SHARE = 0.10

    /**
     * Turns a finished run into advice. An hour whose basal would go UP is held at the current value when glucose
     * went low in that hour on at least [LOW_DAY_SHARE] of days or went very low (below 54) at all. Decreases are never held.
     * [readings] are the readings of the tuned days (excluded days already removed).
     */
    fun advise(result: AutotuneResult, readings: List<AtReading>, zone: ZoneId): AutotuneAdvice {
        val perHour = Array(24) { HashMap<java.time.LocalDate, Boolean>() } // date -> had a low
        val veryLow = BooleanArray(24)
        for (r in readings) {
            val t = Instant.ofEpochMilli(r.timeMs).atZone(zone)
            val h = t.hour
            val low = r.mgdl < 70
            perHour[h][t.toLocalDate()] = (perHour[h][t.toLocalDate()] ?: false) || low
            if (r.mgdl < 54) veryLow[h] = true
        }
        // how much glucose moves in each hour of the day (local time), over the used days
        val sorted = readings.sortedBy { it.timeMs }
        val times = LongArray(sorted.size) { sorted[it].timeMs }
        val values = DoubleArray(sorted.size) { sorted[it].mgdl }
        val perHourSwing = Array(24) { SwingSum() }
        Swing.steps(times, values) { i, j, d, hrs ->
            // a step across the hour boundary belongs to neither hour, so a swing in one hour does not flag its neighbour
            val h1 = Instant.ofEpochMilli(times[i]).atZone(zone).hour
            if (h1 == Instant.ofEpochMilli(times[j]).atZone(zone).hour) perHourSwing[h1].add(d, hrs)
        }
        val swings = perHourSwing.map { if (it.hours >= MIN_SWING_HOURS) it.perHour else null }
        val typical = swings.filterNotNull().sorted().let { if (it.isEmpty()) null else it[it.size / 2] }
        val hours = (0..23).map { h ->
            val cur = result.original.basal[h]
            val new = result.tuned.basal[h]
            val days = perHour[h].size
            val lowDays = perHour[h].values.count { it }
            val lowsHere = veryLow[h] || (days > 0 && lowDays.toDouble() / days >= LOW_DAY_SHARE)
            val held = if (new > cur + 1e-9 && lowsHere) "glucose went low in this hour on $lowDays of $days days" else null
            val untuned = result.tuned.basalUnTuned[h] - result.original.basalUnTuned[h]
            val conf = when {
                result.daysTuned < 5 || untuned >= result.daysTuned / 2 -> Confidence.LOW
                result.daysTuned >= 10 && untuned == 0 -> Confidence.HIGH
                else -> Confidence.MEDIUM
            }
            val swing = swings[h]
            val unsteady = swing != null && typical != null && swing > UNSTEADY_RATIO * typical && swing >= UNSTEADY_FLOOR_MGDL_PER_H
            val finalConf = if (!unsteady) conf else when (conf) { Confidence.HIGH -> Confidence.MEDIUM; else -> Confidence.LOW }
            HourAdvice(h, cur, new, if (held != null) cur else new, held, finalConf, swing, unsteady)
        }
        return AutotuneAdvice(
            hours, result.original.isf, result.tuned.isf, result.original.ic, result.tuned.ic, result.daysTuned, result.mealsUsed, result.isfPoints,
            if (values.isEmpty()) null else TimeInRange.of(values.toList()).cvPct, Swing.of(times, values).perHour,
        )
    }
}
