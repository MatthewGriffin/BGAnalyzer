package app.bganalyzer.sync

import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * Works out which time spans a sync needs to ask Nightscout for, so it never re-downloads what it already has.
 * Pure code, tested without a database.
 *
 * A span is needed when it is part of the chosen period and:
 * - it has never been checked (not in the saved coverage), or
 * - it is the recent tail (late edits and uploads), or
 * - for glucose and IOB, the stored data has a hole there and the hole ended within the last 7 days.
 *   AAPS uploads its queue late after being offline, so recent holes are asked for again each sync.
 *   Holes older than 7 days are asked for once, then trusted as real (the sensor or phone was off).
 * Treatments cannot show holes in the data (they are sparse by nature), so they rely on coverage and the tail.
 */
/**
 * Names under which sync coverage is saved. The suffix is bumped when the way a source is requested changes, so
 * stretches that were checked the old way are checked again once. (Version 2 of treatments and IOB also asks by
 * the event's own `date`, not only by `created_at`, which differs on records uploaded late.)
 */
object Sources {
    const val GLUCOSE = "glucose"
    const val TREATMENTS = "treatments.v2"
    const val IOB = "iob.v2"
    val LEGACY = listOf("treatments", "iob")
}

object SyncPlanner {
    const val DAY_MS = 24L * 60 * 60 * 1000
    const val GLUCOSE_TAIL_MS = 60L * 60 * 1000
    const val IOB_TAIL_MS = 60L * 60 * 1000
    /** Treatments are edited and invalidated later, so look back further than for glucose. */
    const val TREATMENT_TAIL_MS = DAY_MS
    const val RECHECK_RECENT_MS = 7 * DAY_MS
    const val GLUCOSE_GAP_MS = 15L * 60 * 1000
    const val IOB_GAP_MS = 60L * 60 * 1000
    /** Spans closer together than this are asked for as one. */
    const val COALESCE_MS = 30L * 60 * 1000
    const val MAX_SPANS_PER_QUERY = 100

    private val ISO = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'").withZone(ZoneOffset.UTC)

    /**
     * Nightscout stores `created_at` as ISO text with milliseconds in one fixed format, so comparing the
     * text is the same as comparing the time.
     */
    fun iso(ms: Long): String = ISO.format(Instant.ofEpochMilli(ms))

    fun period(nowMs: Long, days: Int) = Span(nowMs - days * DAY_MS, nowMs)

    /** Holes in sorted [timestamps] that are longer than [minGapMs], ended within the recheck window, and touch [period]. */
    fun recentGaps(timestamps: List<Long>, period: Span, nowMs: Long, minGapMs: Long): List<Span> {
        val out = ArrayList<Span>()
        for (i in 1 until timestamps.size) {
            val a = timestamps[i - 1]; val b = timestamps[i]
            if (b - a > minGapMs && b >= nowMs - RECHECK_RECENT_MS) Intervals.clamp(Span(a, b), period)?.let(out::add)
        }
        return out
    }

    /** All spans to request for one kind of data, merged and in time order. */
    fun spans(period: Span, covered: List<Span>, extra: List<Span>, tailMs: Long, nowMs: Long): List<Span> {
        val tail = Span(maxOf(period.startMs, nowMs - tailMs), nowMs)
        val all = Intervals.subtract(period, covered) + extra.mapNotNull { Intervals.clamp(it, period) } + tail
        return Intervals.merge(all, COALESCE_MS)
    }

    /** Each group goes in one request. */
    fun chunks(spans: List<Span>): List<List<Span>> = spans.chunked(MAX_SPANS_PER_QUERY)

    /**
     * Coverage for data stored before coverage was tracked: stretches where readings follow each other without a
     * hole longer than [maxGapMs] count as checked, and the holes between them do not.
     */
    fun coverageFromRuns(sortedTimestamps: List<Long>, maxGapMs: Long): List<Span> {
        if (sortedTimestamps.isEmpty()) return emptyList()
        val out = ArrayList<Span>()
        var start = sortedTimestamps[0]
        var prev = start
        for (t in sortedTimestamps.drop(1)) {
            if (t - prev > maxGapMs) { out.add(Span(start - 1, prev)); start = t }
            prev = t
        }
        out.add(Span(start - 1, prev))
        return out
    }

    /**
     * The longest stretch of [period] (ignoring its last day, which the tail keeps fresh) that any kind of data has
     * never been requested for. Zero when the period is complete.
     */
    fun unsyncedMs(coverage: List<Pair<String, Span>>, period: Span): Long {
        val settled = Span(period.startMs, maxOf(period.startMs, period.endMs - DAY_MS))
        return listOf(Sources.GLUCOSE, Sources.TREATMENTS, Sources.IOB).maxOf { source ->
            Intervals.subtract(settled, coverage.filter { it.first == source }.map { it.second }).sumOf { it.lengthMs }
        }
    }
}
