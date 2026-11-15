package app.bganalyzer.domain

import app.bganalyzer.data.TreatmentEntity
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Which days have any record of insulin being delivered. A day with none is not a quiet day: the pump was off or
 * failed and insulin went unrecorded (pens), so glucose that day says nothing about basal or sensitivity.
 * Pure code.
 */
object DayQuality {
    /** A loop writes a temp basal about every 5 minutes, so this many in a day is clear evidence of a running pump. */
    const val MIN_TEMP_BASALS = 20

    /** Local dates (ISO text) with at least one bolus (SMB included) or [MIN_TEMP_BASALS] credible temp basals. */
    fun daysWithInsulin(treatments: List<TreatmentEntity>, zone: ZoneId): Set<String> {
        val boluses = HashSet<String>()
        val temps = HashMap<String, Int>()
        for (t in treatments) {
            if (!t.valid) continue
            val day = day(t.timestampMs, zone)
            if ((t.insulin ?: 0.0) > 0.0) boluses += day
            else if (t.eventType == "Temp Basal" && t.rateUph != null && (t.durationMs ?: 0L) in 1..BasalTimeline.MAX_TEMP_MS) temps.merge(day, 1, Int::plus)
        }
        return boluses + temps.filterValues { it >= MIN_TEMP_BASALS }.keys
    }

    /**
     * Days in [fromMs, toMs) that have glucose readings but no insulin records, oldest first. The last two days are left
     * out because records can still be on their way from the pump.
     */
    fun daysWithoutInsulin(treatments: List<TreatmentEntity>, readingTimes: List<Long>, zone: ZoneId, fromMs: Long, toMs: Long, nowMs: Long): List<String> {
        val with = daysWithInsulin(treatments, zone)
        val recent = setOf(day(nowMs, zone), day(nowMs - 86_400_000L, zone))
        val firstDay = day(fromMs, zone)
        return readingTimes.filter { it in fromMs until toMs }.map { day(it, zone) }.distinct().sorted()
            .filter { it !in with && it !in recent && it > firstDay }
    }

    private fun day(ms: Long, zone: ZoneId): String = LocalDate.ofInstant(Instant.ofEpochMilli(ms), zone).toString()
}
