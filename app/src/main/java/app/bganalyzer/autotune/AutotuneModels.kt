// Ported from AndroidAPS 3.4.2.1 (commit 1393357107a2b27ba153df31d64e745efd771ef2), plugins/aps/.../autotune/data
// and core/interfaces/.../utils/Round.kt. Copyright the AndroidAPS contributors, licensed under AGPL-3.0 (see LICENSE).
package app.bganalyzer.autotune

import java.math.BigDecimal
import kotlin.math.roundToLong

/** AAPS `Round.roundTo`: round to the nearest multiple of [step] (half up), through BigDecimal as AAPS does. */
internal object AtRound {
    fun roundTo(x: Double, step: Double): Double {
        require(!x.isNaN()) { "Parameter is NaN" }
        return if (x == 0.0) 0.0 else BigDecimal.valueOf((x / step).roundToLong()).multiply(BigDecimal.valueOf(step)).toDouble()
    }
}

/** One categorised glucose reading. Times are epoch milliseconds, glucose in mg/dL. */
data class BgDatum(
    val date: Long,
    val glucose: Double = 0.0,
    val avgDelta: Double = 0.0,
    val bgi: Double = 0.0,
    val deviation: Double = 0.0,
    /** "start" or "end" for the first and last reading of a meal absorption, otherwise empty. */
    val mealAbsorption: String = "",
    val mealCarbs: Int = 0,
)

/** One meal for the carb-ratio calculation. */
data class CrDatum(
    val initialBg: Double,
    val initialIob: Double,
    val endBg: Double,
    val endIob: Double,
    val carbs: Double,
    val insulin: Double,
)

data class DiaDeviation(val dia: Double, val meanDeviation: Double, val smrDeviation: Double = 0.0, val rmsDeviation: Double)
data class PeakDeviation(val peak: Int, val meanDeviation: Double, val smrDeviation: Double = 0.0, val rmsDeviation: Double)

/** Glucose sorted into the groups autotune tunes basal, ISF and carb ratio from. */
data class PreppedGlucose(
    val crData: List<CrDatum>,
    val csfGlucose: List<BgDatum>,
    val isfGlucose: List<BgDatum>,
    val basalGlucose: List<BgDatum>,
    val diaDeviations: List<DiaDeviation> = emptyList(),
    val peakDeviations: List<PeakDeviation> = emptyList(),
)

/** A profile as autotune sees it: one ISF, one carb ratio, and 24 hourly basal rates. ISF in mg/dL per unit. */
data class AtProfile(
    val basal: List<Double>,
    val isf: Double,
    val ic: Double,
    val dia: Double = 6.0,
    val peak: Int = 75,
    /** How many times each hour was filled in from its neighbours because it had no data. */
    val basalUnTuned: List<Int> = List(24) { 0 },
) {
    init { require(basal.size == 24) { "autotune works on 24 hourly basal rates" } }
}

/** Autosens limits and the minimum 5 minute carb impact that bound what autotune may change. */
data class AutotuneLimits(val autosensMax: Double = 1.2, val autosensMin: Double = 0.7, val min5mCarbImpact: Double = 8.0)
