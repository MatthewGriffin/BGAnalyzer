package app.bganalyzer.domain

import app.bganalyzer.data.ProfileEntity
import org.bson.Document

/** Insulin sensitivity (mg/dL per U) and carb ratio (g per U) schedules from an uploaded profile. */
data class ProfileSettings(val isf: List<BasalStep>, val carbRatio: List<BasalStep>) {
    private fun at(steps: List<BasalStep>, hour: Int): Double? =
        if (steps.isEmpty()) null else (steps.lastOrNull { it.secondsFromMidnight <= hour * 3600 } ?: steps.last()).rateUph

    /**
     * As AAPS applies a switch: a percentage above 100 means more insulin, so sensitivity and carb ratio are divided by it;
     * the shift moves the schedule later by whole hours.
     */
    fun modified(percentage: Int, shiftHours: Int): ProfileSettings {
        fun f(steps: List<BasalStep>): List<BasalStep> {
            if (steps.isEmpty()) return steps
            fun original(sec: Int) = (steps.lastOrNull { it.secondsFromMidnight <= Math.floorMod(sec - shiftHours * 3600, 86_400) } ?: steps.last()).rateUph
            val starts = (steps.map { Math.floorMod(it.secondsFromMidnight + shiftHours * 3600, 86_400) } + 0).distinct().sorted()
            return starts.map { BasalStep(it, original(it) * 100.0 / percentage.coerceAtLeast(1)) }
        }
        return ProfileSettings(f(isf), f(carbRatio))
    }

    fun isfMgdlAt(hour: Int) = at(isf, hour)
    fun carbRatioAt(hour: Int) = at(carbRatio, hour)

    companion object {
        val NONE = ProfileSettings(emptyList(), emptyList())

        /** Reads the default profile of [profile]. mmol/L profiles are converted to mg/dL. */
        fun of(profile: ProfileEntity?): ProfileSettings {
            profile ?: return NONE
            val doc = runCatching { Document.parse(profile.rawJson) }.getOrNull() ?: return NONE
            val store = doc["store"] as? Document ?: return NONE
            val main = (profile.defaultProfile?.let { store[it] } ?: store.values.firstOrNull()) as? Document ?: return NONE
            return fromDocument(main, main["units"] as? String ?: profile.units ?: doc["units"] as? String)
        }

        /** Reads a profile body (the `profileJson` of a switch or effective record). */
        fun fromJson(json: String?, percentage: Int = 100, shiftHours: Int = 0): ProfileSettings {
            val d = json?.let { runCatching { Document.parse(it) }.getOrNull() } ?: return NONE
            val base = fromDocument(d, d["units"] as? String)
            return if (percentage == 100 && shiftHours == 0) base else base.modified(percentage, shiftHours)
        }

        private fun fromDocument(main: Document, unitsText: String?): ProfileSettings {
            val unit = GlucoseUnit.fromNightscout(unitsText)
            val factor = if (unit == GlucoseUnit.MMOL) GlucoseUnit.MMOLL_TO_MGDL else 1.0
            fun steps(key: String, scale: Double) = (main[key] as? List<*>).orEmpty().mapNotNull { row ->
                val d = row as? Document ?: return@mapNotNull null
                val sec = (d["timeAsSeconds"] as? Number)?.toInt()
                    ?: (d["time"] as? String)?.split(":")?.let { p -> p.getOrNull(0)?.toIntOrNull()?.let { h -> h * 3600 + (p.getOrNull(1)?.toIntOrNull() ?: 0) * 60 } }
                    ?: return@mapNotNull null
                BasalStep(sec, ((d["value"] as? Number)?.toDouble() ?: return@mapNotNull null) * scale)
            }.sortedBy { it.secondsFromMidnight }
            var isf = steps("sens", factor)
            // Units missing: an ISF under 25 cannot be mg/dL per unit, so it is mmol/L (guards an 18x error).
            if (unit == null && isf.isNotEmpty() && isf.maxOf { it.rateUph } < 25) isf = isf.map { it.copy(rateUph = it.rateUph * GlucoseUnit.MMOLL_TO_MGDL) }
            return ProfileSettings(isf, steps("carbratio", 1.0))
        }
    }
}
