package app.bganalyzer.domain

/**
 * Finds the last time the profile really changed, so Autotune can leave out days run on an older profile.
 * Switching to the same settings again, or a temporary percentage switch, is not a change.
 */
object ProfileChanges {
    private const val RATE_TOLERANCE = 0.0005

    /** The latest non-temporary entry started by [nowMs] that differs from the one before it; null if there was none. */
    fun lastRealChange(entries: List<EffectiveProfile>, nowMs: Long): EffectiveProfile? {
        val steady = entries.filter { !it.isTemporary && it.startMs <= nowMs }.sortedBy { it.startMs }
        var last: EffectiveProfile? = null
        for (i in 1 until steady.size) if (!sameSettings(steady[i - 1], steady[i])) last = steady[i]
        return last
    }

    /** The profile Autotune should start from: the latest non-temporary one in force at [nowMs] (a running temporary switch is ignored). */
    fun baseline(entries: List<EffectiveProfile>, nowMs: Long): EffectiveProfile? =
        entries.filter { !it.isTemporary && it.startMs <= nowMs }.maxByOrNull { it.startMs }

    /** Same basal for every hour, same ISF and carb ratio for every hour (when both know them) and the same insulin duration. */
    fun sameSettings(a: EffectiveProfile, b: EffectiveProfile): Boolean {
        fun close(x: Double?, y: Double?, tol: Double) = x == y || (x != null && y != null && kotlin.math.abs(x - y) <= tol)
        for (h in 0..23) {
            val sec = h * 3600
            val ra = a.basal.lastOrNull { it.secondsFromMidnight <= sec } ?: a.basal.lastOrNull()
            val rb = b.basal.lastOrNull { it.secondsFromMidnight <= sec } ?: b.basal.lastOrNull()
            if (!close(ra?.rateUph, rb?.rateUph, RATE_TOLERANCE)) return false
            val sa = a.settings; val sb = b.settings
            // only compare what both records carry
            if (sa.isf.isNotEmpty() && sb.isf.isNotEmpty() && !close(sa.isfMgdlAt(h), sb.isfMgdlAt(h), 0.01)) return false
            if (sa.carbRatio.isNotEmpty() && sb.carbRatio.isNotEmpty() && !close(sa.carbRatioAt(h), sb.carbRatioAt(h), 0.001)) return false
        }
        val da = a.settings.diaHours; val db = b.settings.diaHours
        return da == null || db == null || kotlin.math.abs(da - db) < 0.01
    }
}
