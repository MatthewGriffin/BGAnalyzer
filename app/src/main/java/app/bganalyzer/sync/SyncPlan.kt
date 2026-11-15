package app.bganalyzer.sync

/** Decides which part of history to fetch. Pure so it can be tested without a database. */
object SyncPlan {
    const val FIRST_SYNC_DAYS = 90L
    /** Re-read this much before the newest stored reading, so late-arriving readings are not missed. Upserts make the repeat harmless. */
    const val OVERLAP_MS = 60 * 60 * 1000L
    private const val DAY_MS = 24 * 60 * 60 * 1000L

    /** The time to fetch from (exclusive), given the newest stored reading or null when there are none. */
    fun fetchAfter(newestStoredMs: Long?, nowMs: Long): Long =
        if (newestStoredMs == null) nowMs - FIRST_SYNC_DAYS * DAY_MS else newestStoredMs - OVERLAP_MS
}
