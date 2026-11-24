package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import java.time.Instant
import java.time.ZoneId

/** One stretch of glucose below the low limit: readings less than [GAP_MS] apart all below it. */
data class LowEpisode(val startMs: Long, val endMs: Long, val lowestMgdl: Double) {
    /** At least one reading interval, so a single low reading is not zero minutes. */
    val minutes get() = ((endMs - startMs) / 60_000L).toInt().coerceAtLeast(READING_MINUTES) 

    companion object { const val READING_MINUTES = 5 }
}

data class LowSummary(
    val episodes: List<LowEpisode>,
    /** Episodes started per hour of day (local), 24 entries. */
    val perHour: List<Int>,
) {
    val count get() = episodes.size
    val averageMinutes get() = if (episodes.isEmpty()) 0 else episodes.sumOf { it.minutes } / episodes.size
    val lowestMgdl get() = episodes.minOfOrNull { it.lowestMgdl }
    /** The hour of day with the most episodes, or null with none. */
    val worstHour get() = perHour.withIndex().maxByOrNull { it.value }?.takeIf { it.value > 0 }?.index
    val veryLowEpisodes get() = episodes.count { it.lowestMgdl < 54 }
}

object Lows {
    const val GAP_MS = 20L * 60 * 1000

    fun summarize(points: List<GlucoseReadingEntity>, zone: ZoneId, lowBelow: Double = 70.0): LowSummary {
        val sorted = points.sortedBy { it.timestampMs }
        val out = ArrayList<LowEpisode>()
        var start = 0L; var end = 0L; var min = 0.0; var open = false
        for (p in sorted) {
            if (p.mgdl < lowBelow) {
                if (open && p.timestampMs - end <= GAP_MS) { end = p.timestampMs; min = minOf(min, p.mgdl) }
                else {
                    if (open) out += LowEpisode(start, end, min)
                    start = p.timestampMs; end = p.timestampMs; min = p.mgdl; open = true
                }
            } else if (open && p.timestampMs - end > GAP_MS) { out += LowEpisode(start, end, min); open = false }
            else if (open) { out += LowEpisode(start, end, min); open = false }
        }
        if (open) out += LowEpisode(start, end, min)
        val perHour = MutableList(24) { 0 }
        out.forEach { perHour[Instant.ofEpochMilli(it.startMs).atZone(zone).hour]++ }
        return LowSummary(out, perHour)
    }
}
