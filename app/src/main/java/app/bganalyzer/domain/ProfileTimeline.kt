package app.bganalyzer.domain

import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import org.bson.Document
import java.time.Instant
import java.time.ZoneId

/**
 * A profile as it was in force from [startMs]: which profile, what modifier (percentage and time shift) was
 * on it, and the basal schedule with that modifier already applied.
 * A temporary switch ([durationMs] above zero) ends by itself and the previous profile resumes.
 */
data class EffectiveProfile(
    val startMs: Long,
    val name: String?,
    val percentage: Int,
    val timeshiftHours: Int,
    val durationMs: Long,
    /** Basal steps with [percentage] and [timeshiftHours] applied. */
    val basal: List<BasalStep>,
    val source: Source,
    /** Sensitivity and carb ratio of this profile with the modifier applied; empty when the record had none. */
    val settings: ProfileSettings = ProfileSettings.NONE,
) {
    enum class Source { EFFECTIVE_RECORD, SWITCH_RECORD, UPLOADED_PROFILE }

    val isTemporary get() = durationMs > 0
    val endMs get() = if (isTemporary) startMs + durationMs else Long.MAX_VALUE
    val hasModifier get() = percentage != 100 || timeshiftHours != 0

    /** Short text for the chart note: the name, the modifier, and the length of a temporary switch. */
    fun label(): String = buildString {
        append(name ?: "Profile")
        if (percentage != 100) append(" ").append(percentage).append("%")
        if (timeshiftHours != 0) append(" ").append(if (timeshiftHours > 0) "+" else "").append(timeshiftHours).append("h")
        if (isTemporary) append(" (").append(durationMs / 60_000).append(" min)")
    }
}

/**
 * Works out which profile was active at any moment, the way AAPS does. Pure code, tested without a database.
 *
 * AAPS records every profile change twice in Nightscout:
 * - a **Profile Switch** (what was asked for): the original profile with a percentage and time shift to apply, and
 * - an **effective profile switch** (a Note with `profileJson`): the profile that actually runs, with the percentage
 *   and shift already applied.
 * The effective record is used when there is one, so the modifier is never applied twice. A switch without one is
 * applied here. A profile edit only takes effect at the next switch, so the uploaded profile documents are only a
 * fallback for time before the first switch.
 */
object ProfileTimeline {
    private const val PAIR_BEFORE_MS = 60_000L
    private const val PAIR_AFTER_MS = 5 * 60_000L
    private const val DAY_SECONDS = 86_400

    /** The treatments that describe profile changes: switches and effective-profile notes. */
    fun isProfileEvent(t: TreatmentEntity) = t.valid && (t.eventType == "Profile Switch" || (t.eventType == "Note" && t.rawJson.contains("\"profileJson\"")))

    fun entries(events: List<TreatmentEntity>): List<EffectiveProfile> {
        val docs = events.filter(::isProfileEvent).sortedBy { it.timestampMs }.map { it to parse(it.rawJson) }
        val effective = docs.filter { it.first.eventType == "Note" && it.second?.get("originalProfileName") != null && it.second?.get("profileJson") is String }
        val switches = docs.filter { it.first.eventType == "Profile Switch" }
        val usedEffective = HashSet<String>()
        val out = ArrayList<EffectiveProfile>()
        for ((t, d) in switches) {
            d ?: continue
            // The effective record made for this switch (one to a few minutes after it); the latest one wins.
            val pair = effective.filter { (e, _) -> e.timestampMs in (t.timestampMs - PAIR_BEFORE_MS)..(t.timestampMs + PAIR_AFTER_MS) }.lastOrNull()
            pair?.let { usedEffective.add(it.first.id) }
            val percentage = (d["percentage"] as? Number)?.toInt() ?: 100
            val shift = hours(d["timeshift"])
            val duration = (d["originalDuration"] as? Number)?.toLong() ?: ((d["duration"] as? Number)?.toLong() ?: 0L) * 60_000L
            val name = (d["originalProfileName"] as? String) ?: (d["profile"] as? String)
            val effectiveSteps = pair?.second?.let { basalOf(it["profileJson"] as? String) }?.takeIf { it.isNotEmpty() }
            val baseSteps = basalOf(d["profileJson"] as? String).orEmpty()
            val steps = effectiveSteps ?: applyModifier(baseSteps, percentage, shift)
            if (steps.isEmpty()) continue
            val settings = if (pair != null && effectiveSteps != null) ProfileSettings.fromJson(pair.second?.get("profileJson") as? String)
                else ProfileSettings.fromJson(d["profileJson"] as? String, percentage, shift)
            out += EffectiveProfile(
                t.timestampMs, name, percentage, shift, duration, steps,
                if (effectiveSteps != null) EffectiveProfile.Source.EFFECTIVE_RECORD else EffectiveProfile.Source.SWITCH_RECORD,
                settings,
            )
        }
        // An effective record with no switch next to it (the switch was not synced) still tells what was running.
        for ((e, d) in effective) {
            if (e.id in usedEffective || d == null) continue
            val steps = basalOf(d["profileJson"] as? String).orEmpty().ifEmpty { continue }
            out += EffectiveProfile(
                e.timestampMs, d["originalProfileName"] as? String, (d["originalPercentage"] as? Number)?.toInt() ?: 100,
                hours(d["originalTimeshift"]), (d["originalDuration"] as? Number)?.toLong() ?: 0L, steps, EffectiveProfile.Source.EFFECTIVE_RECORD,
                ProfileSettings.fromJson(d["profileJson"] as? String),
            )
        }
        return out.sortedBy { it.startMs }
    }

    /** The profile in force at [t]: the latest started, skipping temporary switches that have run out. Null if none had started. */
    fun activeAt(entries: List<EffectiveProfile>, t: Long): EffectiveProfile? =
        entries.filter { it.startMs <= t }.sortedBy { it.startMs }.lastOrNull { !it.isTemporary || t < it.endMs }

    /** The basal rate (U/h) a schedule gives at [timeMs], in the profile's local time. */
    fun rateAt(steps: List<BasalStep>, timeMs: Long, zone: ZoneId): Double? {
        if (steps.isEmpty()) return null
        val sec = Instant.ofEpochMilli(timeMs).atZone(zone).toLocalTime().toSecondOfDay()
        return (steps.lastOrNull { it.secondsFromMidnight <= sec } ?: steps.last()).rateUph
    }

    /**
     * What AAPS does to a schedule for a switch: the rate at a time of day is the original rate at that time minus the
     * shift, times the percentage. Returned as ordinary steps.
     */
    fun applyModifier(steps: List<BasalStep>, percentage: Int, shiftHours: Int): List<BasalStep> {
        if (steps.isEmpty() || (percentage == 100 && shiftHours == 0)) return steps
        fun original(sec: Int): Double {
            val shifted = Math.floorMod(sec - shiftHours * 3600, DAY_SECONDS)
            return (steps.lastOrNull { it.secondsFromMidnight <= shifted } ?: steps.last()).rateUph
        }
        val starts = (steps.map { Math.floorMod(it.secondsFromMidnight + shiftHours * 3600, DAY_SECONDS) } + 0).distinct().sorted()
        return starts.map { BasalStep(it, original(it) * percentage / 100.0) }
    }

    /** The profile to assume before any switch is known: the uploaded profile document in effect at [t] (the first if none yet). */
    fun fallback(profiles: List<ProfileEntity>, t: Long): EffectiveProfile? {
        val sorted = profiles.sortedBy { it.startMs }
        val p = sorted.lastOrNull { it.startMs <= t } ?: sorted.firstOrNull() ?: return null
        val steps = BasalTimeline.schedule(p).ifEmpty { return null }
        return EffectiveProfile(p.startMs, null, 100, 0, 0, steps, EffectiveProfile.Source.UPLOADED_PROFILE)
    }

    private fun parse(raw: String): Document? = runCatching { Document.parse(raw) }.getOrNull()

    /** NS stores the shift in milliseconds when AAPS uploads it and in hours when it is entered in Nightscout. */
    private fun hours(v: Any?): Int {
        val n = (v as? Number)?.toDouble() ?: return 0
        return if (kotlin.math.abs(n) >= 1000) (n / 3_600_000.0).toInt() else n.toInt()
    }

    /** The basal schedule inside a `profileJson` string. */
    private fun basalOf(json: String?): List<BasalStep>? {
        val doc = json?.let { parse(it) } ?: return null
        return (doc["basal"] as? List<*>).orEmpty().mapNotNull { row ->
            val d = row as? Document ?: return@mapNotNull null
            val sec = (d["timeAsSeconds"] as? Number)?.toInt()
                ?: (d["time"] as? String)?.split(":")?.let { p -> p.getOrNull(0)?.toIntOrNull()?.let { h -> h * 3600 + (p.getOrNull(1)?.toIntOrNull() ?: 0) * 60 } }
                ?: return@mapNotNull null
            BasalStep(sec, (d["value"] as? Number)?.toDouble() ?: return@mapNotNull null)
        }.sortedBy { it.secondsFromMidnight }
    }
}

/** Answers "what basal does the profile in force give at this moment?" for any time. */
class ProfileResolver(private val entries: List<EffectiveProfile>, private val uploaded: List<ProfileEntity>) {
    private val sortedEntries = entries.sortedBy { it.startMs }
    private val fallbacks = HashMap<Long, EffectiveProfile?>()

    fun at(timeMs: Long): EffectiveProfile? = ProfileTimeline.activeAt(sortedEntries, timeMs)
        ?: fallbacks.getOrPut(uploaded.sortedBy { it.startMs }.lastOrNull { it.startMs <= timeMs }?.startMs ?: -1L) { ProfileTimeline.fallback(uploaded, timeMs) }

    /** Sensitivity and carb ratio of the profile in force at [timeMs], or of the newest uploaded profile before it. */
    fun settingsAt(timeMs: Long): ProfileSettings =
        at(timeMs)?.settings?.takeIf { it.isf.isNotEmpty() || it.carbRatio.isNotEmpty() }
            ?: ProfileSettings.of(uploaded.sortedBy { it.startMs }.lastOrNull { it.startMs <= timeMs } ?: uploaded.minByOrNull { it.startMs })

    fun basalAt(timeMs: Long, zone: ZoneId): Double? = at(timeMs)?.let { ProfileTimeline.rateAt(it.basal, timeMs, zone) }

    /** Profile changes for the chart and the profile list, oldest first. */
    fun changes(fromMs: Long, toMs: Long): List<EffectiveProfile> = sortedEntries.filter { it.startMs in fromMs..toMs }

    companion object {
        /** A resolver that only knows uploaded profile documents (no switch records). */
        fun fromUploaded(profiles: List<ProfileEntity>) = ProfileResolver(emptyList(), profiles)
    }
}
