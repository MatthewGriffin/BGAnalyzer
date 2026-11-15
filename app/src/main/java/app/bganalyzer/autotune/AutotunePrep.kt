// Ported from AndroidAPS 3.4.2.1 (commit 1393357107a2b27ba153df31d64e745efd771ef2), autotune/AutotunePrep.kt
// (itself a port of oref0 lib/autotune-prep/categorize.js and dosed.js).
// Copyright the AndroidAPS contributors, licensed under AGPL-3.0 (see LICENSE).
package app.bganalyzer.autotune

import java.time.Instant
import java.time.ZoneId
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.pow
import kotlin.math.roundToInt

/** One glucose reading. [mgdl] in mg/dL. */
data class AtReading(val timeMs: Long, val mgdl: Double)

/** Carbs entered at one time. */
data class AtMeal(val timeMs: Long, val carbs: Double)

/** Everything one day's categorisation needs. */
class PrepInput(
    /** Readings in the day, any order. */
    val readings: List<AtReading>,
    /** Carb entries, any order. Only entries after the first reading count. */
    val meals: List<AtMeal>,
    /** Boluses plus the net basal doses from [AutotuneDoses.build]. */
    val doses: List<Dose>,
)

data class PrepOptions(
    /** Also try other insulin end times and peak times and report which fits best (AAPS "tune insulin curve"). */
    val tuneInsulinCurve: Boolean = false,
    /** Count all unannounced-meal readings as basal data (AAPS "categorize UAM as basal"). */
    val uamAsBasal: Boolean = false,
)

object AutotunePrep {
    /**
     * Sorts one day's glucose into the groups autotune tunes from, as AAPS does. [tuned] is the profile being tuned
     * (its ISF, carb ratio and hourly basal), [min5mCarbImpact] the minimum carb impact per 5 minutes.
     * Returns null when there is no usable glucose or no insulin data.
     */
    fun categorize(input: PrepInput, tuned: AtProfile, zone: ZoneId, min5mCarbImpact: Double, options: PrepOptions = PrepOptions(), log: AutotuneLog = AutotuneLog()): PreppedGlucose? {
        val main = categorizeOnce(input, tuned, LocalInsulin(tuned.peak, tuned.dia), zone, min5mCarbImpact, log, options.uamAsBasal) ?: return null
        if (!options.tuneInsulinCurve) return main
        val dias = ArrayList<DiaDeviation>()
        val peaks = ArrayList<PeakDeviation>()
        var dia = tuned.dia - 2
        while (dia <= tuned.dia + 2) {
            val basal = categorizeOnce(input, tuned, LocalInsulin(tuned.peak, dia), zone, min5mCarbImpact, null, options.uamAsBasal)?.basalGlucose ?: return main
            deviations(basal)?.let { (mean, smr, rms) -> dias += DiaDeviation(dia, mean, smr, rms) }
            dia += 1.0
        }
        var peak = tuned.peak - 10
        while (peak <= tuned.peak + 10) {
            val basal = categorizeOnce(input, tuned, LocalInsulin(peak, tuned.dia), zone, min5mCarbImpact, null, options.uamAsBasal)?.basalGlucose ?: return main
            deviations(basal)?.let { (mean, smr, rms) -> peaks += PeakDeviation(peak, mean, smr, rms) }
            peak += 5
        }
        return main.copy(diaDeviations = dias, peakDeviations = peaks)
    }

    private fun deviations(basal: List<BgDatum>): Triple<Double, Double, Double>? {
        if (basal.isEmpty()) return null
        var sqrt = 0.0; var dev = 0.0; var sq = 0.0
        for (b in basal) { sqrt += abs(b.deviation).pow(0.5); dev += abs(b.deviation); sq += b.deviation.pow(2.0) }
        val n = basal.size
        return Triple(AtRound.roundTo(abs(dev / n), 0.001), AtRound.roundTo((sqrt / n).pow(2.0), 0.001), AtRound.roundTo((sq / n).pow(0.5), 0.001))
    }

    private class Raw(val date: Long, var value: Double)

    private fun categorizeOnce(input: PrepInput, tuned: AtProfile, insulin: LocalInsulin, zone: ZoneId, min5m: Double, log: AutotuneLog?, uamAsBasal: Boolean = false): PreppedGlucose? {
        // newest first, values under 40 mg/dL are sensor errors
        val glucose = input.readings.filter { it.mgdl > 39 }.sortedByDescending { it.timeMs }.map { Raw(it.timeMs, it.mgdl) }
        if (glucose.isEmpty()) { log?.add("No glucose values"); return null }
        if (input.doses.isEmpty()) { log?.add("No insulin data"); return null }
        val oldestBg = glucose.last().date
        // oldest meal last, so the loop below can take them off the end
        val treatments = input.meals.filter { it.carbs > 0 && it.timeMs >= oldestBg }.sortedByDescending { it.timeMs }.toMutableList()
        val iobCurve = IobCurve(input.doses, insulin)

        // bucket readings: readings under 2 minutes apart are averaged
        val bucketed = ArrayList<BgDatum>()
        bucketed.add(BgDatum(glucose[0].date, glucose[0].value))
        var k = 0
        for (i in 1 until glucose.size) {
            val elapsedMinutes = (glucose[i].date - glucose[k].date) / (60 * 1000)
            if (abs(elapsedMinutes) >= 2) {
                k = i
                bucketed.add(BgDatum(glucose[i].date, glucose[i].value))
            } else {
                val average = glucose[k]
                for (l in k + 1 until i + 1) average.value += glucose[l].value
                average.value = average.value / (i - k + 1)
                bucketed.add(BgDatum(average.date, average.value))
            }
        }

        var calculatingCR = false
        var absorbing = false
        var uam = false
        var mealCOB = 0.0
        var mealCarbs = 0.0
        var crCarbs = 0.0
        var type = ""
        var crInitialIOB = 0.0
        var crInitialBG = 0.0
        var crInitialCarbTime = 0L
        val csf = ArrayList<BgDatum>()
        var isf = ArrayList<BgDatum>()
        var basalData = ArrayList<BgDatum>()
        val uamData = ArrayList<BgDatum>()
        val cr = ArrayList<CrDatum>()
        val crTimes = ArrayList<Pair<Long, Long>>()

        val sens = tuned.isf
        for (i in bucketed.size - 5 downTo 1) {
            val datum = bucketed[i]
            val bgTime = datum.date
            // carbs enter the model one entry per reading, once they are older than the reading
            val treatment = treatments.lastOrNull()
            var myCarbs = 0.0
            if (treatment != null && treatment.timeMs < bgTime) {
                if (treatment.carbs > 0.0) { mealCOB += treatment.carbs; mealCarbs += treatment.carbs; myCarbs = treatment.carbs }
                treatments.removeAt(treatments.size - 1)
            }
            var bg = 0.0
            var avgDelta = 0.0
            if (bucketed[i].glucose != 0.0 && bucketed[i + 4].glucose != 0.0) {
                bg = bucketed[i].glucose
                if (bg < 40 || bucketed[i + 4].glucose < 40) continue
                avgDelta = (bg - bucketed[i + 4].glucose) / 4
            }
            avgDelta = AtRound.roundTo(avgDelta, 0.01)
            datum.avgDelta = avgDelta

            val currentBasal = tuned.basal[Instant.ofEpochMilli(bgTime).atZone(zone).hour]
            // BGI of basal insulin: U/h * mg/dL/U / 60 * 5 = mg/dL per 5 minutes
            val basalBGI = AtRound.roundTo(currentBasal * sens / 60 * 5, 0.01)
            val iob = iobCurve.at(bgTime)
            val bgi = AtRound.roundTo(-iob.activity * sens * 5, 0.01)
            datum.bgi = bgi
            var deviation = avgDelta - bgi
            if (bg < 80 && deviation > 0) deviation = 0.0
            deviation = AtRound.roundTo(deviation, 0.01)
            datum.deviation = deviation

            if (mealCOB > 0) {
                val ci = max(deviation, min5m)
                val absorbed = ci * tuned.ic / sens
                mealCOB = max(0.0, mealCOB - absorbed)
            }

            // carb ratio: from the carbs until COB is zero and IOB has dropped below half the basal
            if (mealCOB > 0 || calculatingCR) {
                crCarbs += myCarbs
                if (!calculatingCR) {
                    crInitialIOB = iob.iob
                    crInitialBG = datum.glucose
                    crInitialCarbTime = datum.date
                }
                if (mealCOB > 0 && i > 1) {
                    calculatingCR = true
                } else if (iob.iob > currentBasal / 2 && i > 1) {
                    calculatingCR = true
                } else {
                    val crEndTime = datum.date
                    val crElapsedMinutes = ((crEndTime - crInitialCarbTime) / (1000 * 60).toFloat()).roundToInt()
                    if (crElapsedMinutes < 60 || i == 1 && mealCOB > 0) {
                        // too short, or still absorbing when the data ends: ignored
                    } else {
                        cr.add(CrDatum(crInitialBG, crInitialIOB, datum.glucose, iob.iob, crCarbs, 0.0))
                        crTimes.add(crInitialCarbTime to crEndTime)
                    }
                    crCarbs = 0.0
                    calculatingCR = false
                }
            }

            if (mealCOB > 0 || absorbing || mealCarbs > 0) {
                absorbing = if (iob.iob < currentBasal / 2) false else deviation > 0
                if (!absorbing && mealCOB == 0.0) mealCarbs = 0.0
                if (type != "csf") datum.mealAbsorption = "start"
                type = "csf"
                datum.mealCarbs = mealCarbs.toInt()
                csf.add(datum)
            } else {
                if (type == "csf") csf[csf.size - 1].mealAbsorption = "end"
                if (iob.iob > 2 * currentBasal || deviation > 6 || uam) {
                    uam = deviation > 0
                    type = "uam"
                    uamData.add(datum)
                } else {
                    // basal insulin activity dominates: tune basal; clear insulin activity: tune ISF
                    if (basalBGI > -4 * bgi) {
                        type = "basal"
                        basalData.add(datum)
                    } else if (avgDelta > 0 && avgDelta > -2 * bgi) {
                        type = "basal"
                        basalData.add(datum)
                    } else {
                        type = "ISF"
                        isf.add(datum)
                    }
                }
            }
        }

        val crData = cr.mapIndexed { n, d -> d.copy(insulin = dosed(crTimes[n].first, crTimes[n].second, input.doses)) }
        var csfData: List<BgDatum> = csf
        val csfLength = csf.size
        val isfLength = isf.size
        val uamLength = uamData.size
        val basalLength = basalData.size
        // sort as AAPS does: deviations are rounded to 0.01, so compare them times 100 as truncated ints
        val byDeviation = Comparator<BgDatum> { a, b -> (100 * a.deviation - 100 * b.deviation).toInt() }
        if (uamAsBasal) {
            basalData.addAll(uamData)
        } else if (csfLength > 12) {
            // an hour or more of carb absorption: meals were announced, so unexplained rises are basal
            basalData.addAll(uamData)
        } else {
            if (2 * basalLength < uamLength) {
                basalData.addAll(uamData)
                basalData.sortWith(byDeviation)
                basalData = ArrayList(basalData.subList(0, basalData.size / 2))
            }
            if (2 * isfLength < uamLength) {
                isf.addAll(uamData)
                isf.sortWith(byDeviation)
                isf = ArrayList(isf.subList(0, isf.size / 2))
            }
        }
        if (4 * basalData.size + isf.size < csfLength && isf.size < 10) {
            // too much of the data was called meals: use it for ISF instead
            isf.addAll(csf)
            csfData = emptyList()
        }
        log?.add("Sorted glucose: ${crData.size} meals, ${csfData.size} carb absorption, ${isf.size} insulin only, ${basalData.size} basal readings")
        return PreppedGlucose(crData, csfData, isf, basalData)
    }

    /** Insulin given after [start] up to and including [end] (basal doses included, as in AAPS). */
    private fun dosed(start: Long, end: Long, doses: List<Dose>): Double {
        if (doses.isEmpty()) return 0.0
        var total = 0.0
        for (d in doses) if (d.units != 0.0 && d.timeMs > start && d.timeMs <= end) total += d.units
        return AtRound.roundTo(total, 0.001)
    }
}
