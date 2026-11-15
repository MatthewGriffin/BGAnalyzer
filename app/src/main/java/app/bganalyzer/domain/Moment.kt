package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.IobSampleEntity
import app.bganalyzer.data.TreatmentEntity

/** What was going on at one moment, for the touch-and-slide readout on the chart. */
data class MomentSummary(
    val timeMs: Long,
    /** The reading nearest the moment, if one is within [Moment.MAX_READING_GAP_MS]. */
    val mgdl: Double?,
    val readingOffsetMs: Long,
    val basal: BasalSegment?,
    val carbsLast3h: Double,
    val bolusLast3h: Double,
    /** The most recent carb entry at or before the moment, and how long before. */
    val lastCarbs: Pair<Double, Long>?,
    /** The most recent insulin bolus (units, whether automatic, how long before). */
    val lastBolus: Triple<Double, Boolean, Long>?,
    /** Insulin and carbs on board as last reported by the loop at or before the moment (within [Moment.MAX_IOB_AGE_MS]). */
    val iob: IobSampleEntity? = null,
)

object Moment {
    const val MAX_READING_GAP_MS = 10 * 60_000L
    const val MAX_IOB_AGE_MS = 30 * 60_000L
    private const val WINDOW_MS = 3 * 3_600_000L

    /** [readings] must be sorted by time. [treatments] are valid treatments, any order. */
    fun at(
        timeMs: Long,
        readings: List<GlucoseReadingEntity>,
        treatments: List<TreatmentEntity>,
        basal: List<BasalSegment>,
        iob: List<IobSampleEntity> = emptyList(),
    ): MomentSummary {
        val nearest = nearest(readings, timeMs)?.takeIf { kotlin.math.abs(it.timestampMs - timeMs) <= MAX_READING_GAP_MS }
        val before = treatments.filter { it.valid && it.timestampMs <= timeMs }
        val recent = before.filter { timeMs - it.timestampMs <= WINDOW_MS }
        val carbEvents = before.filter { (it.carbs ?: 0.0) > 0 }
        val bolusEvents = before.filter { (it.insulin ?: 0.0) > 0 }
        return MomentSummary(
            timeMs = timeMs,
            mgdl = nearest?.mgdl,
            readingOffsetMs = nearest?.let { it.timestampMs - timeMs } ?: 0L,
            basal = basal.firstOrNull { timeMs >= it.startMs && timeMs < it.endMs },
            carbsLast3h = recent.sumOf { it.carbs ?: 0.0 },
            bolusLast3h = recent.sumOf { it.insulin ?: 0.0 },
            lastCarbs = carbEvents.maxByOrNull { it.timestampMs }?.let { it.carbs!! to timeMs - it.timestampMs },
            lastBolus = bolusEvents.maxByOrNull { it.timestampMs }?.let { Triple(it.insulin!!, it.isSmb, timeMs - it.timestampMs) },
            iob = iob.filter { it.timestampMs <= timeMs && timeMs - it.timestampMs <= MAX_IOB_AGE_MS }.maxByOrNull { it.timestampMs },
        )
    }

    /** The glucose (mg/dL) at [t]: the nearest reading within [maxGapMs], or null. [readings] must be sorted by time. */
    fun glucoseNear(readings: List<GlucoseReadingEntity>, t: Long, maxGapMs: Long = 15 * 60_000L): Double? =
        nearest(readings, t)?.takeIf { kotlin.math.abs(it.timestampMs - t) <= maxGapMs }?.mgdl

    private fun nearest(readings: List<GlucoseReadingEntity>, t: Long): GlucoseReadingEntity? {
        if (readings.isEmpty()) return null
        var lo = 0; var hi = readings.size
        while (lo < hi) { val mid = (lo + hi) ushr 1; if (readings[mid].timestampMs < t) lo = mid + 1 else hi = mid }
        val a = readings.getOrNull(lo - 1); val b = readings.getOrNull(lo)
        return listOfNotNull(a, b).minByOrNull { kotlin.math.abs(it.timestampMs - t) }
    }
}
