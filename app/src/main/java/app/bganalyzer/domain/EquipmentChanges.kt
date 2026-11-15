package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.TreatmentEntity

/** A site, insulin (reservoir) or sensor change the user logged. Changes logged together are one entry. */
data class EquipmentChange(val startMs: Long, val kinds: List<String>) {
    val label: String get() = kinds.joinToString(" + ")
}

data class EquipmentResult(val change: EquipmentChange, val before: PeriodSummary, val after: PeriodSummary)

/**
 * Before and after glucose for changes that are not profile changes: infusion site, insulin cartridge and sensor.
 * Uses the same windows as [ChangeComparison]: up to 7 days either side, stopping at the neighbouring change.
 * It shows what happened, not why.
 */
object EquipmentChanges {
    /** Nightscout event types, and the short name shown for each. */
    val EVENT_TYPES = mapOf(
        "Site Change" to "Site",
        "Insulin Change" to "Insulin",
        "Sensor Start" to "Sensor",
        "Sensor Change" to "Sensor",
    )
    /** AAPS logs a site and an insulin change a moment apart when both are done; these count as one change. */
    const val MERGE_MS = 30 * 60_000L

    /** Equipment changes found in [treatments], oldest first, with those within [MERGE_MS] of each other joined. */
    fun from(treatments: List<TreatmentEntity>): List<EquipmentChange> {
        val events = treatments.filter { it.valid }
            .mapNotNull { t -> EVENT_TYPES[t.eventType]?.let { t.timestampMs to it } }
            .sortedBy { it.first }
        val out = ArrayList<EquipmentChange>()
        for ((time, kind) in events) {
            val last = out.lastOrNull()
            if (last != null && time - last.startMs <= MERGE_MS) {
                if (kind !in last.kinds) out[out.size - 1] = last.copy(kinds = (last.kinds + kind).sorted())
            } else out += EquipmentChange(time, listOf(kind))
        }
        return out
    }

    /** [readings] sorted by time and stripped of excluded days. Only changes at or after [periodFromMs] are reported, oldest first. */
    fun compare(readings: List<GlucoseReadingEntity>, changes: List<EquipmentChange>, periodFromMs: Long, nowMs: Long): List<EquipmentResult> {
        val sorted = changes.sortedBy { it.startMs }
        return sorted.mapIndexedNotNull { i, c ->
            if (c.startMs < periodFromMs) return@mapIndexedNotNull null
            val beforeFrom = maxOf(c.startMs - ChangeComparison.WINDOW_DAYS * ChangeComparison.DAY_MS, sorted.getOrNull(i - 1)?.startMs ?: Long.MIN_VALUE)
            val afterTo = minOf(c.startMs + ChangeComparison.WINDOW_DAYS * ChangeComparison.DAY_MS, sorted.getOrNull(i + 1)?.startMs ?: Long.MAX_VALUE, nowMs)
            EquipmentResult(c, ChangeComparison.summary(readings, beforeFrom, c.startMs), ChangeComparison.summary(readings, c.startMs, afterTo))
        }
    }
}
