package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity

/** One profile configuration and how long it was in force. [endMs] is null for the one in force now. */
data class ProfileConfig(val profile: EffectiveProfile, val endMs: Long?, val summary: PeriodSummary)

/**
 * Past profile configurations with the glucose they saw, newest first, so a change that made time in range worse can be
 * read back and undone by hand. Pure code.
 */
object ProfileHistory {
    const val MAX_CONFIGS = 12
    /** Glucose is summarised over at most this long from the start of a configuration. */
    const val MAX_SPAN_DAYS = 30

    fun build(readings: List<GlucoseReadingEntity>, changes: List<EffectiveProfile>, zone: java.time.ZoneId, nowMs: Long): List<ProfileConfig> {
        val steady = ProfileChanges.dailyChanges(changes, zone).filter { it.startMs <= nowMs }
        return steady.mapIndexed { i, p ->
            val end = steady.getOrNull(i + 1)?.startMs
            val to = minOf(end ?: nowMs, p.startMs + MAX_SPAN_DAYS * ChangeComparison.DAY_MS, nowMs)
            ProfileConfig(p, end, ChangeComparison.summary(readings, p.startMs, to))
        }.asReversed().take(MAX_CONFIGS)
    }
}
