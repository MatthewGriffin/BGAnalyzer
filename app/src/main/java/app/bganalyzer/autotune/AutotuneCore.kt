// Ported from AndroidAPS 3.4.2.1 (commit 1393357107a2b27ba153df31d64e745efd771ef2),
// plugins/aps/.../autotune/AutotuneCore.kt. Copyright the AndroidAPS contributors, licensed under AGPL-3.0 (see LICENSE).
package app.bganalyzer.autotune

import java.time.Instant
import java.time.ZoneId
import kotlin.math.max

/** What a tuning run did, in plain sentences, for the explanation shown to the user. */
class AutotuneLog { val lines = ArrayList<String>(); fun add(s: String) { lines += s } }

object AutotuneCore {
    /**
     * Tunes one day's worth of [prepped] data from [previous] (the profile before this day), bounded by [pump]
     * (the original profile) and [limits]. Hours of day are in [zone]. Pure: returns a new profile.
     */
    fun tune(prepped: PreppedGlucose, previous: AtProfile, pump: AtProfile, limits: AutotuneLimits, zone: ZoneId, log: AutotuneLog = AutotuneLog()): AtProfile {
        val hourlyBasal = previous.basal
        val isf = previous.isf
        val carbRatio = previous.ic
        val csf = isf / carbRatio
        val dia = previous.dia
        val peak = previous.peak
        val pumpISF = pump.isf
        val pumpCarbRatio = pump.ic
        val pumpCSF = pumpISF / pumpCarbRatio
        val autotuneMax = limits.autosensMax
        val autotuneMin = limits.autosensMin
        val min5minCarbImpact = limits.min5mCarbImpact

        // tune DIA
        var newDia = dia
        val diaDeviations = prepped.diaDeviations
        if (diaDeviations.isNotEmpty()) {
            val currentMean = diaDeviations[2].meanDeviation
            val currentRms = diaDeviations[2].rmsDeviation
            var minMean = 1000000.0; var minRms = 1000000.0
            var meanBest = 2; var rmsBest = 2
            for (i in diaDeviations.indices) {
                if (diaDeviations[i].meanDeviation < minMean) { minMean = AtRound.roundTo(diaDeviations[i].meanDeviation, 0.001); meanBest = i }
                if (diaDeviations[i].rmsDeviation < minRms) { minRms = AtRound.roundTo(diaDeviations[i].rmsDeviation, 0.001); rmsBest = i }
            }
            if (meanBest < 2 && rmsBest < 2) {
                if (diaDeviations[1].meanDeviation < currentMean * 0.99 && diaDeviations[1].rmsDeviation < currentRms * 0.99) newDia = diaDeviations[1].dia
            } else if (meanBest > 2 && rmsBest > 2) {
                if (diaDeviations[3].meanDeviation < currentMean * 0.99 && diaDeviations[3].rmsDeviation < currentRms * 0.99) newDia = diaDeviations[3].dia
            }
            if (newDia > 12.0) newDia = 12.0
            log.add(if (newDia != dia) "Insulin end time changed from $dia to $newDia hours" else "Insulin end time left at $dia hours")
        }

        // tune insulin peak time
        var newPeak = peak
        val peakDeviations = prepped.peakDeviations
        if (peakDeviations.size > 2) {
            val currentMean = peakDeviations[2].meanDeviation
            val currentRms = peakDeviations[2].rmsDeviation
            var minMean = 1000000.0; var minRms = 1000000.0
            var meanBest = 2; var rmsBest = 2
            for (i in peakDeviations.indices) {
                if (peakDeviations[i].meanDeviation < minMean) { minMean = AtRound.roundTo(peakDeviations[i].meanDeviation, 0.001); meanBest = i }
                if (peakDeviations[i].rmsDeviation < minRms) { minRms = AtRound.roundTo(peakDeviations[i].rmsDeviation, 0.001); rmsBest = i }
            }
            if (meanBest < 2 && rmsBest < 2) {
                if (peakDeviations[1].meanDeviation < currentMean * 0.99 && peakDeviations[1].rmsDeviation < currentRms * 0.99) newPeak = peakDeviations[1].peak
            } else if (meanBest > 2 && rmsBest > 2) {
                if (peakDeviations[3].meanDeviation < currentMean * 0.99 && peakDeviations[3].rmsDeviation < currentRms * 0.99) newPeak = peakDeviations[3].peak
            }
            log.add(if (newPeak != peak) "Insulin peak time changed from $peak to $newPeak minutes" else "Insulin peak time left at $peak minutes")
        }

        // carb ratio from meals: entered carbs against the insulin they needed
        var crTotalCarbs = 0.0
        var crTotalInsulin = 0.0
        for (d in prepped.crData) {
            val insulinReq = (d.endBg - d.initialBg) / isf
            val insulinTotal = d.initialIob + d.insulin + insulinReq
            if (insulinTotal > 0) { crTotalCarbs += d.carbs; crTotalInsulin += insulinTotal }
        }
        crTotalInsulin = AtRound.roundTo(crTotalInsulin, 0.001)
        var totalCR = 0.0
        if (crTotalInsulin != 0.0) totalCR = AtRound.roundTo(crTotalCarbs / crTotalInsulin, 0.001)

        // basal: net deviations for each hour
        val newHourly = DoubleArray(24) { hourlyBasal[it] }
        val basalUnTuned = previous.basalUnTuned.toIntArray()
        for (hour in 0..23) {
            var deviations = 0.0
            for (b in prepped.basalGlucose) {
                if (b.date == 0L) continue
                if (Instant.ofEpochMilli(b.date).atZone(zone).hour == hour) deviations += b.deviation
            }
            deviations = AtRound.roundTo(deviations, 0.001)
            // only apply 20% of the needed adjustment to keep things relatively stable
            val basalNeeded = AtRound.roundTo(0.2 * deviations / isf, 0.01)
            if (basalNeeded > 0) {
                for (offset in -3..-1) {
                    val h = Math.floorMod(hour + offset, 24)
                    newHourly[h] = AtRound.roundTo(newHourly[h] + basalNeeded / 3, 0.001)
                }
            } else if (basalNeeded < 0) {
                var threeHour = 0.0
                for (offset in -3..-1) threeHour += newHourly[Math.floorMod(hour + offset, 24)]
                val ratio = 1.0 + basalNeeded / threeHour
                for (offset in -3..-1) {
                    val h = Math.floorMod(hour + offset, 24)
                    newHourly[h] = AtRound.roundTo(newHourly[h] * ratio, 0.001)
                }
            }
        }
        // cap at the autosens limits of the pump profile
        for (hour in 0..23) {
            val maxRate = pump.basal[hour] * autotuneMax
            val minRate = pump.basal[hour] * autotuneMin
            if (newHourly[hour] > maxRate) newHourly[hour] = maxRate
            else if (newHourly[hour] < minRate) newHourly[hour] = minRate
            newHourly[hour] = AtRound.roundTo(newHourly[hour], 0.001)
        }
        // hours with no adjustment move toward the average of the nearest adjusted hours
        var lastAdjustedHour = 0
        for (hour in 0..23) {
            if (hourlyBasal[hour] == newHourly[hour]) {
                var nextAdjustedHour = 23
                for (nextHour in hour..23) {
                    if (hourlyBasal[nextHour] != newHourly[nextHour]) { nextAdjustedHour = nextHour; break }
                }
                newHourly[hour] = AtRound.roundTo(0.8 * hourlyBasal[hour] + 0.1 * newHourly[lastAdjustedHour] + 0.1 * newHourly[nextAdjustedHour], 0.001)
                basalUnTuned[hour]++
            } else lastAdjustedHour = hour
        }

        // carb sensitivity factor from deviations while carbs absorb
        var deviations = 0.0
        var mealCarbs = 0
        var totalMealCarbs = 0
        var totalDeviations = 0.0
        for (c in prepped.csfGlucose) {
            if (c.mealAbsorption == "start") {
                deviations = 0.0
                mealCarbs = c.mealCarbs
            } else if (c.mealAbsorption == "end") {
                deviations += c.deviation
                totalMealCarbs += mealCarbs
                totalDeviations += deviations
            } else {
                deviations += max(0 * min5minCarbImpact, c.deviation)
                mealCarbs = max(mealCarbs, c.mealCarbs)
            }
        }
        if (totalMealCarbs == 0) totalMealCarbs += mealCarbs
        if (totalDeviations == 0.0) totalDeviations += deviations
        val fullNewCSF = if (totalMealCarbs == 0) csf else AtRound.roundTo(totalDeviations / totalMealCarbs, 0.01)
        // (the new CSF itself is computed by AAPS but not used for the profile; only the carb ratio below is)

        var fullNewCR = if (totalCR == 0.0) carbRatio else totalCR
        var maxCR = pumpCarbRatio * autotuneMax
        if (maxCR > 150) maxCR = 150.0
        var minCR = pumpCarbRatio * autotuneMin
        if (minCR < 3) minCR = 3.0
        if (pumpCarbRatio != 0.0) {
            if (fullNewCR > maxCR) fullNewCR = maxCR else if (fullNewCR < minCR) fullNewCR = minCR
        }
        var newCR = 0.8 * carbRatio + 0.2 * fullNewCR
        if (pumpCarbRatio != 0.0) {
            if (newCR > maxCR) newCR = maxCR else if (newCR < minCR) newCR = minCR
        }
        newCR = AtRound.roundTo(newCR, 0.001)
        val finalCarbRatio = if (newCR != 0.0) newCR else carbRatio

        // ISF from the median deviation attributable to insulin
        val ratios = ArrayList<Double>()
        for (g in prepped.isfGlucose) ratios.add(1 + g.deviation / g.bgi)
        ratios.sort()
        val count = prepped.isfGlucose.size
        val p50ratios = AtRound.roundTo(percentile(ratios, 0.50), 0.001)
        var fullNewISF = isf
        if (count >= 10) fullNewISF = isf * p50ratios
        fullNewISF = AtRound.roundTo(fullNewISF, 0.001)
        val adjustmentFraction = 1.0
        val maxISF = pumpISF / autotuneMin
        val minISF = pumpISF / autotuneMax
        var newISF = 0.0
        if (pumpISF != 0.0) {
            var adjustedISF = if (fullNewISF < 0) isf else adjustmentFraction * fullNewISF + (1 - adjustmentFraction) * pumpISF
            if (adjustedISF > maxISF) adjustedISF = maxISF else if (adjustedISF < minISF) adjustedISF = minISF
            newISF = 0.8 * isf + 0.2 * adjustedISF
            if (newISF > maxISF) newISF = maxISF else if (newISF < minISF) newISF = minISF
        }
        newISF = AtRound.roundTo(newISF, 0.001)
        val finalISF = if (newISF != 0.0) newISF else isf
        log.add("Carb sensitivity would change from ${AtRound.roundTo(csf, 0.001)} to $fullNewCSF (used for context only)")
        log.add("Carb ratio ${AtRound.roundTo(carbRatio, 0.001)} -> $finalCarbRatio, sensitivity ${AtRound.roundTo(isf, 0.001)} -> $finalISF (from $count insulin-only readings)")

        return AtProfile(newHourly.toList(), finalISF, AtRound.roundTo(finalCarbRatio, 0.001), newDia, newPeak, basalUnTuned.toList())
    }

    /** AAPS `Percentile.percentile` on a sorted list. */
    internal fun percentile(sorted: List<Double>, p: Double): Double =
        if (sorted.isEmpty()) 0.0 else sorted[minOf(sorted.size - 1, (sorted.size * p).toInt())]
}
