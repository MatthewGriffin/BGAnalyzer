package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import java.time.Instant
import java.time.ZoneId

/** Glucose summary for one time of day, such as 00:00-06:00, across many days. */
data class BlockStats(
    val startHour: Int,
    val endHour: Int,
    /** Days with enough readings in this block to count (see [TimeBlocks.MIN_COVERAGE]). */
    val days: Int,
    val readings: Int,
    val timeInRange: TimeInRange,
    /** Days with at least one reading below the low limit / the very-low limit. */
    val lowDays: Int,
    val veryLowDays: Int,
) {
    val enoughDays get() = days >= TimeBlocks.MIN_DAYS
}

/** Splits readings by local time of day. Pure: no database, no Android. */
object TimeBlocks {
    /** A block on a day counts only if at least this share of its expected readings (one per 5 minutes) is present. */
    const val MIN_COVERAGE = 0.5
    /** Fewer days than this are shown with a "not enough data" note rather than as a pattern. */
    const val MIN_DAYS = 5
    val ALLOWED_BLOCK_HOURS = listOf(2, 3, 4, 6, 8, 12)

    /** Local (zone) hour of day for a time. Uses the zone's real rules, so DST days are handled. */
    fun localHour(timeMs: Long, zone: ZoneId): Int = Instant.ofEpochMilli(timeMs).atZone(zone).hour

    fun analyze(
        readings: List<GlucoseReadingEntity>,
        zone: ZoneId,
        blockHours: Int,
        ranges: GlucoseRanges = GlucoseRanges(),
    ): List<BlockStats> {
        require(blockHours in ALLOWED_BLOCK_HOURS) { "block size must divide 24" }
        val blocks = 24 / blockHours
        // One cell per (local date, block): the readings that fall in that block on that day.
        val cells = HashMap<Pair<java.time.LocalDate, Int>, MutableList<Double>>()
        for (r in readings) {
            val local = Instant.ofEpochMilli(r.timestampMs).atZone(zone)
            cells.getOrPut(local.toLocalDate() to local.hour / blockHours) { ArrayList() }.add(r.mgdl)
        }
        val expected = blockHours * 12
        return (0 until blocks).map { b ->
            val used = cells.filter { it.key.second == b && it.value.size >= expected * MIN_COVERAGE }.values
            val all = used.flatten()
            BlockStats(
                startHour = b * blockHours,
                endHour = (b + 1) * blockHours,
                days = used.size,
                readings = all.size,
                timeInRange = TimeInRange.of(all, ranges),
                lowDays = used.count { cell -> cell.any { it < ranges.lowBelow } },
                veryLowDays = used.count { cell -> cell.any { it < ranges.veryLowBelow } },
            )
        }
    }
}
