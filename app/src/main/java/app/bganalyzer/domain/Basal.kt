package app.bganalyzer.domain

import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import org.bson.Document
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime

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
    fun build(
        treatments: List<TreatmentEntity>,
        profiles: List<ProfileEntity>,
        fromMs: Long,
        toMs: Long,
        zone: ZoneId,
    ): List<BasalSegment> {
        val temps = treatments.filter { it.eventType == "Temp Basal" && it.valid && it.rateUph != null && it.durationMs != null }
            .sortedBy { it.timestampMs }
        val result = ArrayList<BasalSegment>()
        var cursor = fromMs
        for ((i, t) in temps.withIndex()) {
            val end = minOf(t.timestampMs + t.durationMs!!, temps.getOrNull(i + 1)?.timestampMs ?: Long.MAX_VALUE, toMs)
            val start = maxOf(t.timestampMs, fromMs)
            if (end <= start) continue
            if (start > cursor) fillScheduled(result, profiles, cursor, start, zone)
            result += BasalSegment(start, end, t.rateUph!!, scheduled = false)
            cursor = end
        }
        if (cursor < toMs) fillScheduled(result, profiles, cursor, toMs, zone)
        return result
    }

    private fun fillScheduled(out: MutableList<BasalSegment>, profiles: List<ProfileEntity>, from: Long, to: Long, zone: ZoneId) {
        if (profiles.isEmpty()) return
        val sorted = profiles.sortedBy { it.startMs }
        // Boundaries inside the gap: every schedule step and every profile change.
        val cuts = sortedSetOf(from, to)
        sorted.filter { it.startMs in (from + 1) until to }.forEach { cuts.add(it.startMs) }
        var day: LocalDate = Instant.ofEpochMilli(from).atZone(zone).toLocalDate()
        val lastDay = Instant.ofEpochMilli(to).atZone(zone).toLocalDate()
        while (!day.isAfter(lastDay)) {
            val steps = (sorted.lastOrNull { it.startMs <= from } ?: sorted.first()).let { schedule(it) }
            for (s in steps) {
                val ms = ZonedDateTime.of(day, LocalTime.ofSecondOfDay(s.secondsFromMidnight.toLong()), zone).toInstant().toEpochMilli()
                if (ms in (from + 1) until to) cuts.add(ms)
            }
            day = day.plusDays(1)
        }
        val points = cuts.toList()
        for (i in 0 until points.size - 1) {
            val a = points[i]; val b = points[i + 1]
            val profile = sorted.lastOrNull { it.startMs <= a } ?: sorted.first()
            val steps = schedule(profile)
            if (steps.isEmpty()) continue
            val sec = Instant.ofEpochMilli(a).atZone(zone).toLocalTime().toSecondOfDay()
            // Before the first step of the day the previous day's last rate still applies.
            val rate = (steps.lastOrNull { it.secondsFromMidnight <= sec } ?: steps.last()).rateUph
            out += BasalSegment(a, b, rate, scheduled = true)
        }
    }
}
