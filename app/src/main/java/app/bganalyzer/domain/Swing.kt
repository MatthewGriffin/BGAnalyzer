package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity

/** Total absolute glucose change and the time it was measured over, so several stretches can be pooled. */
class SwingSum {
    var absDeltaMgdl = 0.0
    var hours = 0.0
    fun add(delta: Double, h: Double) { absDeltaMgdl += delta; hours += h }
    fun add(other: SwingSum) { absDeltaMgdl += other.absDeltaMgdl; hours += other.hours }
    /** Average rate of change in mg/dL per hour, or null with nothing measured. 0 is a flat line. */
    val perHour: Double? get() = if (hours > 0) absDeltaMgdl / hours else null
}

/**
 * How much glucose moves, regardless of where it sits: the average absolute rate of change. A flat line is 0 and a
 * heart-monitor trace is high, even when every reading is in range (which time in range and CV alone cannot tell apart:
 * a steady 4 to 9 mmol/L sawtooth is 100% in range with a CV under 30%).
 * Steps are about 15 minutes, so sensor jitter does not count as swing, and a step is used only when its two readings are
 * at most 20 minutes apart, so a gap in the data adds nothing. Pure code.
 */
object Swing {
    const val STEP_MS = 15 * 60_000L
    const val MAX_GAP_MS = 20 * 60_000L

    /** Calls [onStep] with (first index, second index, absolute change, hours) for every usable step. [times] must be ascending. */
    fun steps(times: LongArray, values: DoubleArray, onStep: (Int, Int, Double, Double) -> Unit) {
        var j = 0
        for (i in times.indices) {
            if (j <= i) j = i + 1
            while (j < times.size && times[j] - times[i] < STEP_MS) j++
            if (j < times.size && times[j] - times[i] <= MAX_GAP_MS) {
                onStep(i, j, kotlin.math.abs(values[j] - values[i]), (times[j] - times[i]) / 3_600_000.0)
            }
        }
    }

    fun of(times: LongArray, values: DoubleArray): SwingSum = SwingSum().also { sum -> steps(times, values) { _, _, d, h -> sum.add(d, h) } }

    fun of(readings: List<GlucoseReadingEntity>): SwingSum {
        val sorted = readings.sortedBy { it.timestampMs }
        return of(LongArray(sorted.size) { sorted[it].timestampMs }, DoubleArray(sorted.size) { sorted[it].mgdl })
    }
}
