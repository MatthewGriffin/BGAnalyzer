// Ported from AndroidAPS 3.4.2.1 (commit 1393357107a2b27ba153df31d64e745efd771ef2): autotune/data/LocalInsulin.kt and
// the IOB handling of autotune/AutotuneIob.kt. Copyright the AndroidAPS contributors, licensed under AGPL-3.0 (see LICENSE).
package app.bganalyzer.autotune

import app.bganalyzer.domain.BasalSegment
import java.time.Instant
import java.time.ZoneId
import kotlin.math.ceil
import kotlin.math.exp
import kotlin.math.pow

/** An amount of insulin taken at one moment. Basal is turned into many small doses of this kind. */
data class Dose(val timeMs: Long, val units: Double)

/** Insulin on board and its activity (units of insulin acting per minute) at one moment. */
data class IobTotal(val timeMs: Long, val iob: Double, val activity: Double)

/** The exponential insulin curve AAPS uses for autotune, set by the insulin end time ([diaHours]) and [peakMinutes]. */
class LocalInsulin(val peakMinutes: Int = DEFAULT_PEAK, private val userDiaHours: Double = DEFAULT_DIA) {
    val diaHours get() = if (userDiaHours >= MIN_DIA) userDiaHours else MIN_DIA
    val durationMs get() = (60 * 60 * 1000L * diaHours).toLong()

    /** Returns (iob, activity) left from [units] given at [doseTimeMs], measured at [timeMs]. */
    fun contribution(units: Double, doseTimeMs: Long, timeMs: Long): Pair<Double, Double> {
        if (units == 0.0) return 0.0 to 0.0
        val t = (timeMs - doseTimeMs) / 1000.0 / 60.0
        val td = diaHours * 60
        val tp = peakMinutes.toDouble()
        if (t >= td) return 0.0 to 0.0
        val tau = tp * (1 - tp / td) / (1 - 2 * tp / td)
        val a = 2 * tau / td
        val s = 1 / (1 - a + (1 + a) * exp(-td / tau))
        val activity = units * (s / tau.pow(2.0)) * t * (1 - t / td) * exp(-t / tau)
        val iob = units * (1 - s * (1 - a) * ((t.pow(2.0) / (tau * td * (1 - a)) - t / tau - 1) * exp(-t / tau) + 1))
        return iob to activity
    }

    companion object {
        const val MIN_DIA = 5.0
        const val DEFAULT_DIA = 6.0
        const val DEFAULT_PEAK = 75
    }
}

/**
 * The doses autotune counts for IOB: real boluses (including SMBs), plus basal as a stream of small doses.
 * Each stretch of basal (temp basal, or the scheduled profile where none ran) becomes one dose every five minutes or so,
 * sized as the rate actually delivered minus the rate of the profile being tuned, so a basal equal to the tuned profile
 * adds no insulin. This is how AAPS and oref0 autotune keep "normal" basal out of IOB.
 */
object AutotuneDoses {
    private const val HOUR_MS = 3_600_000L

    /**
     * [basal] covers the period completely (temp basals plus scheduled basal), as `BasalTimeline.build` returns it.
     * [tunedBasalAt] gives the tuned profile's rate in U/h at a time (hourly in [zone]).
     */
    fun build(boluses: List<Dose>, basal: List<BasalSegment>, tuned: AtProfile, zone: ZoneId): List<Dose> {
        val out = ArrayList<Dose>(boluses)
        for (seg in basal) splitByHour(seg, tuned, zone, out)
        return out.sortedBy { it.timeMs }
    }

    /**
     * An extended bolus as many small doses, one about every five minutes, each in the middle of its slice (AAPS
     * `convertToBoluses(EB)`). AAPS multiplies the slice length by 60,000 a second time there, which would push the
     * doses far into the future; this keeps the slices inside the bolus.
     */
    fun extended(timeMs: Long, durationMs: Long, units: Double): List<Dose> {
        if (durationMs <= 0 || units == 0.0) return emptyList()
        val count = (durationMs / (5 * 60_000L) + 1).toInt()
        val spacing = durationMs / count.toDouble()
        return (0 until count).map { j -> Dose((timeMs + j * spacing + 0.5 * spacing).toLong(), units / count) }
    }

    private fun msFromMidnight(t: Long, zone: ZoneId) = Instant.ofEpochMilli(t).atZone(zone).toLocalTime().toNanoOfDay() / 1_000_000L

    private fun splitByHour(seg: BasalSegment, tuned: AtProfile, zone: ZoneId, out: MutableList<Dose>) {
        var ts = seg.startMs
        var remaining = seg.endMs - seg.startMs
        if (remaining / 60_000L <= 0) return
        val end = ts + remaining
        while (remaining > 0) {
            if (msFromMidnight(ts, zone) / HOUR_MS == msFromMidnight(end, zone) / HOUR_MS) {
                pieces(ts, remaining, seg.rateUph, tuned, zone, out)
                remaining = 0
            } else {
                val filled = HOUR_MS - msFromMidnight(ts, zone) % HOUR_MS
                pieces(ts, filled, seg.rateUph, tuned, zone, out)
                ts += filled
                remaining -= filled
            }
        }
    }

    /** One stretch inside one hour, as five-minute doses of (delivered - tuned) basal. */
    private fun pieces(startMs: Long, durationMs: Long, rateUph: Double, tuned: AtProfile, zone: ZoneId, out: MutableList<Dose>) {
        val minutes = durationMs / 60_000L // whole minutes, as AAPS
        if (minutes <= 0) return
        val tunedRate = tuned.basal[Instant.ofEpochMilli(startMs).atZone(zone).hour]
        val net = AtRound.roundTo(rateUph - tunedRate, 0.001)
        val count = ceil(minutes / 5.0).toInt()
        val spacing = minutes / count.toDouble()
        for (j in 0 until count) {
            val time = (startMs + j * spacing * 60 * 1000 + 0.5 * spacing * 60 * 1000).toLong()
            out += Dose(time, net * spacing / 60.0)
        }
    }
}

/** IOB at any moment from a list of doses, as autotune computes it (rounded to 0.001). */
class IobCurve(doses: List<Dose>, private val insulin: LocalInsulin) {
    private val sorted = doses.sortedBy { it.timeMs }
    private val times = LongArray(sorted.size) { sorted[it].timeMs }

    fun at(timeMs: Long): IobTotal {
        var iob = 0.0; var activity = 0.0
        // doses from one insulin duration ago up to now
        var i = lowerBound(timeMs - insulin.durationMs)
        while (i < sorted.size && sorted[i].timeMs <= timeMs) {
            val (a, b) = insulin.contribution(sorted[i].units, sorted[i].timeMs, timeMs)
            iob += a; activity += b
            i++
        }
        return IobTotal(timeMs, AtRound.roundTo(iob, 0.001), AtRound.roundTo(activity, 0.001))
    }

    private fun lowerBound(t: Long): Int {
        var lo = 0; var hi = times.size
        while (lo < hi) { val mid = (lo + hi) ushr 1; if (times[mid] < t) lo = mid + 1 else hi = mid }
        return lo
    }
}
