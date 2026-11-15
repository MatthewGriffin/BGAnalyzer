package app.bganalyzer.autotune

import app.bganalyzer.domain.Confidence
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
)

data class AutotuneAdvice(
    val hours: List<HourAdvice>,
    val currentIsf: Double, val tunedIsf: Double,
    val currentCarbRatio: Double, val tunedCarbRatio: Double,
    val daysTuned: Int,
    val mealsUsed: Int = 0,
    val isfPoints: Int = 0,
)

object AutotuneAdvisor {
    /** Fewer meals than this over the run makes the carb ratio low confidence; fewer insulin-only readings does the same for the ISF. */
    const val MIN_MEALS = 10
    const val MIN_ISF_POINTS = 20

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
            HourAdvice(h, cur, new, if (held != null) cur else new, held, conf)
        }
        return AutotuneAdvice(hours, result.original.isf, result.tuned.isf, result.original.ic, result.tuned.ic, result.daysTuned, result.mealsUsed, result.isfPoints)
    }
}
