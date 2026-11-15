package app.bganalyzer.domain

import app.bganalyzer.data.ProfileEntity
import org.bson.Document

/** Insulin sensitivity (mg/dL per U) and carb ratio (g per U) schedules from an uploaded profile. */
data class ProfileSettings(val isf: List<BasalStep>, val carbRatio: List<BasalStep>) {
    private fun at(steps: List<BasalStep>, hour: Int): Double? =
        if (steps.isEmpty()) null else (steps.lastOrNull { it.secondsFromMidnight <= hour * 3600 } ?: steps.last()).rateUph

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
            val unit = GlucoseUnit.fromNightscout(main["units"] as? String ?: profile.units ?: doc["units"] as? String)
            val factor = if (unit == GlucoseUnit.MMOL) GlucoseUnit.MMOLL_TO_MGDL else 1.0
            fun steps(key: String, scale: Double) = (main[key] as? List<*>).orEmpty().mapNotNull { row ->
                val d = row as? Document ?: return@mapNotNull null
                val sec = (d["timeAsSeconds"] as? Number)?.toInt()
                    ?: (d["time"] as? String)?.split(":")?.let { p -> p.getOrNull(0)?.toIntOrNull()?.let { h -> h * 3600 + (p.getOrNull(1)?.toIntOrNull() ?: 0) * 60 } }
                    ?: return@mapNotNull null
                BasalStep(sec, ((d["value"] as? Number)?.toDouble() ?: return@mapNotNull null) * scale)
            }.sortedBy { it.secondsFromMidnight }
            return ProfileSettings(steps("sens", factor), steps("carbratio", 1.0))
        }
    }
}
