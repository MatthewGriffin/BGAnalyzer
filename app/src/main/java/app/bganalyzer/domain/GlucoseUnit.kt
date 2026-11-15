package app.bganalyzer.domain

/**
 * Glucose units. Everything is stored in mg/dL, as Nightscout and AAPS do, and converted for display.
 *
 * AAPS uploads profile ISF and targets in the profile's own units, so those values must go through
 * [toMgdl] before use. Treating an mmol/L value as mg/dL is an 18x error.
 */
enum class GlucoseUnit(val label: String) {
    MGDL("mg/dL"),
    MMOL("mmol/L");

    /** Converts a value in this unit to mg/dL. */
    fun toMgdl(value: Double): Double = if (this == MGDL) value else value * MMOLL_TO_MGDL

    /** Converts a mg/dL value to this unit. */
    fun fromMgdl(mgdl: Double): Double = if (this == MGDL) mgdl else mgdl / MMOLL_TO_MGDL

    companion object {
        /** The factor AAPS uses (18.0, not 18.0182), kept the same so results match AAPS. */
        const val MMOLL_TO_MGDL = 18.0

        /** Parses the `units` field of a Nightscout profile. Returns null for anything unrecognised. */
        fun fromNightscout(units: String?): GlucoseUnit? = when (units?.trim()?.lowercase()) {
            "mg/dl", "mgdl" -> MGDL
            "mmol", "mmol/l" -> MMOL
            else -> null
        }
    }
}
