package app.bganalyzer.domain

/** Glucose thresholds in mg/dL. The defaults are the international consensus targets (3.0, 3.9, 10.0 and 13.9 mmol/L). */
data class GlucoseRanges(
    val veryLowBelow: Double = 54.0,
    val lowBelow: Double = 70.0,
    val highAbove: Double = 180.0,
    val veryHighAbove: Double = 250.0,
) {
    init {
        require(veryLowBelow < lowBelow && lowBelow < highAbove && highAbove < veryHighAbove) { "ranges must be increasing" }
    }
}

/** How a set of readings splits across the ranges. Percentages are of [count] and add up to 100. */
data class TimeInRange(
    val count: Int,
    val veryLow: Int,
    val low: Int,
    val inRange: Int,
    val high: Int,
    val veryHigh: Int,
    val meanMgdl: Double,
    /** Standard deviation of the readings, mg/dL. */
    val sdMgdl: Double = 0.0,
) {
    private fun pct(n: Int) = if (count == 0) 0.0 else 100.0 * n / count
    val veryLowPct get() = pct(veryLow)
    /** Readings from 54 up to (not including) 70 mg/dL, not counting those below 54. */
    val lowPct get() = pct(low)
    val inRangePct get() = pct(inRange)
    val highPct get() = pct(high)
    val veryHighPct get() = pct(veryHigh)
    /** Coefficient of variation: SD as a percentage of the mean. The consensus target is 36% or less, but that is a low-glucose risk limit, not a measure of flatness (see [Swing]). */
    val cvPct get() = if (meanMgdl > 0) 100.0 * sdMgdl / meanMgdl else 0.0

    companion object {
        val EMPTY = TimeInRange(0, 0, 0, 0, 0, 0, 0.0)

        /**
         * Counts readings per range. CGM readings arrive at a steady interval, so counting readings
         * matches time spent in each range. A reading exactly on a limit counts as in range, except
         * the very-low and very-high limits, which belong to low and high.
         */
        fun of(mgdl: List<Double>, ranges: GlucoseRanges = GlucoseRanges()): TimeInRange {
            if (mgdl.isEmpty()) return EMPTY
            var veryLow = 0; var low = 0; var inRange = 0; var high = 0; var veryHigh = 0
            for (v in mgdl) when {
                v < ranges.veryLowBelow -> veryLow++
                v < ranges.lowBelow -> low++
                v <= ranges.highAbove -> inRange++
                v <= ranges.veryHighAbove -> high++
                else -> veryHigh++
            }
            val mean = mgdl.average()
            val sd = kotlin.math.sqrt(mgdl.sumOf { (it - mean) * (it - mean) } / mgdl.size)
            return TimeInRange(mgdl.size, veryLow, low, inRange, high, veryHigh, mean, sd)
        }
    }
}
