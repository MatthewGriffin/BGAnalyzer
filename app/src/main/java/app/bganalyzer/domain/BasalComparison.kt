package app.bganalyzer.domain

import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import java.time.Instant
import java.time.ZoneId

/**
 * How the loop's actual basal (temp basals) compared with the profile's scheduled basal over one time of day.
 * Percentages are shares of the time a temp basal was running. Rates are time-weighted averages in U/h.
 */
data class BasalBlockStats(
    val startHour: Int,
    val endHour: Int,
    /** Days with enough loop data in this block to count (see [BasalComparison.MIN_COVERAGE]). */
    val days: Int,
    val abovePct: Double,
    val belowPct: Double,
    val atPct: Double,
    /** Share of the time the loop had basal at 0 U/h (included in [belowPct]). */
    val zeroPct: Double,
    val avgActual: Double,
    val avgScheduled: Double,
) {
    val enoughDays get() = days >= TimeBlocks.MIN_DAYS
    /** Actual minus scheduled, as a percentage of scheduled. */
    val changePct get() = if (avgScheduled > 0) (avgActual / avgScheduled - 1) * 100 else 0.0
}

data class BasalComparisonResult(
    /** All hours together: [BasalBlockStats.startHour] 0 to [BasalBlockStats.endHour] 24. */
    val overall: BasalBlockStats,
    val blocks: List<BasalBlockStats>,
    /** Share of the period (with a profile known) in which a temp basal was running. Low means the loop data is incomplete. */
    val loopCoveragePct: Double,
    val tempCount: Int,
    val tempAbove: Int,
    val tempBelow: Int,
    val tempAt: Int,
    val periodDays: Double,
)

/** Pure comparison of temp basals against the profile schedule. Needs no database or Android. */
object BasalComparison {
    /** A rate within this of the schedule counts as "at profile" (pump steps are 0.05 U/h). */
    const val AT_PROFILE_TOLERANCE = 0.025
    /** A block on a day counts only if a temp basal was running for at least this share of it. */
    const val MIN_COVERAGE = 0.5
    private const val MINUTE_MS = 60_000L

    private class Cell {
        var covered = 0L; var above = 0L; var below = 0L; var at = 0L; var zero = 0L
        var actualSum = 0.0; var scheduledSum = 0.0
    }

    /**
     * [treatments] should reach back about 12 hours before [fromMs] so a temp basal already running at the start is included.
     * Time is measured minute by minute in the profile's local time, so DST days have their real length.
     */
    /** Convenience for callers that only have uploaded profile documents (no switch records). */
    fun analyze(
        treatments: List<TreatmentEntity>,
        profiles: List<ProfileEntity>,
        fromMs: Long,
        toMs: Long,
        zone: ZoneId,
        blockHours: Int,
    ): BasalComparisonResult = analyze(treatments, ProfileResolver.fromUploaded(profiles), fromMs, toMs, zone, blockHours)

    /**
     * Compares each minute's temp basal with the basal of the profile that was in force then, including its percentage
     * and time shift ([resolver]).
     */
    fun analyze(
        treatments: List<TreatmentEntity>,
        resolver: ProfileResolver,
        fromMs: Long,
        toMs: Long,
        zone: ZoneId,
        blockHours: Int,
    ): BasalComparisonResult {
        require(blockHours in TimeBlocks.ALLOWED_BLOCK_HOURS)
        val segments = BasalTimeline.tempSegments(treatments, fromMs, toMs)
        val rules = zone.rules
        val cells = HashMap<Pair<Long, Int>, Cell>()
        var segIndex = 0
        var knownMinutes = 0L
        var coveredMinutes = 0L

        var t = (fromMs + MINUTE_MS - 1) / MINUTE_MS * MINUTE_MS
        while (t < toMs) {
            val scheduled = resolver.basalAt(t, zone)
            if (scheduled != null) {
                knownMinutes++
                while (segIndex < segments.size && segments[segIndex].endMs <= t) segIndex++
                val seg = segments.getOrNull(segIndex)?.takeIf { it.startMs <= t }
                if (seg != null) {
                    coveredMinutes++
                    val local = t / 1000 + rules.getOffset(Instant.ofEpochMilli(t)).totalSeconds
                    val day = Math.floorDiv(local, 86_400L)
                    val sec = Math.floorMod(local, 86_400L).toInt()
                    val cell = cells.getOrPut(day to sec / 3600 / blockHours) { Cell() }
                    cell.covered++
                    cell.actualSum += seg.rateUph; cell.scheduledSum += scheduled
                    when {
                        seg.rateUph > scheduled + AT_PROFILE_TOLERANCE -> cell.above++
                        seg.rateUph < scheduled - AT_PROFILE_TOLERANCE -> cell.below++
                        else -> cell.at++
                    }
                    if (seg.rateUph <= 0.0) cell.zero++
                }
            }
            t += MINUTE_MS
        }

        val expected = blockHours * 60
        val counted = cells.filter { it.value.covered >= expected * MIN_COVERAGE }
        fun stats(start: Int, end: Int, use: Map<Pair<Long, Int>, Cell>): BasalBlockStats {
            val c = use.values
            val covered = c.sumOf { it.covered }.coerceAtLeast(1)
            fun pct(n: Long) = 100.0 * n / covered
            return BasalBlockStats(
                start, end, use.keys.map { it.first }.distinct().size,
                pct(c.sumOf { it.above }), pct(c.sumOf { it.below }), pct(c.sumOf { it.at }), pct(c.sumOf { it.zero }),
                avgActual = c.sumOf { it.actualSum } / covered, avgScheduled = c.sumOf { it.scheduledSum } / covered,
            )
        }
        val blocks = (0 until 24 / blockHours).map { b -> stats(b * blockHours, (b + 1) * blockHours, counted.filter { it.key.second == b }) }

        // Per-record view: how each temp basal compared with the schedule when it was set.
        var above = 0; var below = 0; var at = 0; var count = 0
        for (tb in treatments) {
            if (tb.eventType != "Temp Basal" || !tb.valid || tb.rateUph == null || tb.timestampMs !in fromMs until toMs || (tb.durationMs ?: 0L) <= 0L || (tb.durationMs ?: 0L) > BasalTimeline.MAX_TEMP_MS) continue
            val scheduled = resolver.basalAt(tb.timestampMs, zone) ?: continue
            count++
            when {
                tb.rateUph > scheduled + AT_PROFILE_TOLERANCE -> above++
                tb.rateUph < scheduled - AT_PROFILE_TOLERANCE -> below++
                else -> at++
            }
        }
        return BasalComparisonResult(
            overall = stats(0, 24, counted),
            blocks = blocks,
            loopCoveragePct = if (knownMinutes == 0L) 0.0 else 100.0 * coveredMinutes / knownMinutes,
            tempCount = count, tempAbove = above, tempBelow = below, tempAt = at,
            periodDays = (toMs - fromMs) / 86_400_000.0,
        )
    }
}
