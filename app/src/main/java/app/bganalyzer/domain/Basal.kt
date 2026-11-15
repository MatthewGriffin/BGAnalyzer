package app.bganalyzer.domain

import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import org.bson.Document
import java.time.Instant
import java.time.ZoneId

/** A stretch of time with one basal rate. [scheduled] is true when it comes from the profile, not a temp basal. */
data class BasalSegment(val startMs: Long, val endMs: Long, val rateUph: Double, val scheduled: Boolean)

/** One basal schedule entry: from [secondsFromMidnight] (local time) the rate is [rateUph]. */
data class BasalStep(val secondsFromMidnight: Int, val rateUph: Double)

object BasalTimeline {
    /** Reads the basal schedule of the default profile from an uploaded profile document. Empty if it has none. */
    fun schedule(profile: ProfileEntity): List<BasalStep> {
        val doc = runCatching { Document.parse(profile.rawJson) }.getOrNull() ?: return emptyList()
        val store = doc["store"] as? Document ?: return emptyList()
        val main = (profile.defaultProfile?.let { store[it] } ?: store.values.firstOrNull()) as? Document ?: return emptyList()
        return (main["basal"] as? List<*>).orEmpty().mapNotNull { row ->
            val d = row as? Document ?: return@mapNotNull null
            val seconds = (d["timeAsSeconds"] as? Number)?.toInt()
                ?: (d["time"] as? String)?.split(":")?.let { p -> p.getOrNull(0)?.toIntOrNull()?.let { h -> h * 3600 + (p.getOrNull(1)?.toIntOrNull() ?: 0) * 60 } }
                ?: return@mapNotNull null
            val rate = (d["value"] as? Number)?.toDouble() ?: return@mapNotNull null
            BasalStep(seconds, rate)
        }.sortedBy { it.secondsFromMidnight }
    }

    /**
     * Basal rate over [fromMs, toMs): temp basals where one is running, the profile schedule elsewhere.
     * A temp basal ends at its duration or when the next one starts, whichever is first; a record with
     * zero duration just ends the previous one. The schedule is the profile as uploaded: it does not apply
     * profile percentage or time-shift, so scheduled stretches can differ from what the pump really ran.
     * [treatments] should reach back far enough (about 12 hours) to include a temp basal running at [fromMs].
     */
    /** Convenience for callers that only have uploaded profile documents. */
    fun build(treatments: List<TreatmentEntity>, profiles: List<ProfileEntity>, fromMs: Long, toMs: Long, zone: ZoneId): List<BasalSegment> =
        build(treatments, ProfileResolver.fromUploaded(profiles), fromMs, toMs, zone)

    fun build(
        treatments: List<TreatmentEntity>,
        resolver: ProfileResolver,
        fromMs: Long,
        toMs: Long,
        zone: ZoneId,
    ): List<BasalSegment> {
        val result = ArrayList<BasalSegment>()
        var cursor = fromMs
        for (seg in tempSegments(treatments, fromMs, toMs)) {
            if (seg.startMs > cursor) fillScheduled(result, resolver, cursor, seg.startMs, zone)
            result += seg
            cursor = seg.endMs
        }
        if (cursor < toMs) fillScheduled(result, resolver, cursor, toMs, zone)
        return result
    }

    /**
     * Only the temp basals, over [fromMs, toMs): each runs for its duration or until the next one starts, whichever is
     * first; a record with zero duration ends the previous one. Time with no temp basal running is not in the list.
     */
    fun tempSegments(treatments: List<TreatmentEntity>, fromMs: Long, toMs: Long): List<BasalSegment> {
        val temps = treatments.filter { it.eventType == "Temp Basal" && it.valid && it.rateUph != null && it.durationMs != null }
            .sortedBy { it.timestampMs }
        val out = ArrayList<BasalSegment>()
        for ((i, t) in temps.withIndex()) {
            val end = minOf(t.timestampMs + t.durationMs!!, temps.getOrNull(i + 1)?.timestampMs ?: Long.MAX_VALUE, toMs)
            val start = maxOf(t.timestampMs, fromMs)
            if (end > start) out += BasalSegment(start, end, t.rateUph!!, scheduled = false)
        }
        return out
    }

    /** Scheduled basal for a gap, sampled each minute in local time so profile switches, modifiers and DST are all respected. */
    private fun fillScheduled(out: MutableList<BasalSegment>, resolver: ProfileResolver, from: Long, to: Long, zone: ZoneId) {
        var start = from
        var rate: Double? = null
        var t = from
        while (t < to) {
            val r = resolver.basalAt(t, zone)
            if (r != rate) {
                if (rate != null && t > start) out += BasalSegment(start, t, rate, scheduled = true)
                start = t; rate = r
            }
            t += 60_000L
        }
        if (rate != null && to > start) out += BasalSegment(start, to, rate, scheduled = true)
    }
}
