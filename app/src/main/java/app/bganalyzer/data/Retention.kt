package app.bganalyzer.data

/**
 * Old readings, insulin records and treatments are deleted after a sync, so the database stays about the same size however
 * long automatic sync runs. The longest period any tab can show is 90 days, so this keeps a little more than that.
 * Profile switches and the (few) excluded days are kept, since the profile in force at the start of a period comes from them.
 */
object Retention {
    const val KEEP_DAYS = 100
    private const val DAY_MS = 24L * 60 * 60 * 1000

    fun cutoff(nowMs: Long) = nowMs - KEEP_DAYS * DAY_MS

    /** Returns how many glucose readings, treatments and insulin-on-board records were deleted. */
    suspend fun prune(db: AppDatabase, nowMs: Long = System.currentTimeMillis()): Int {
        val cut = cutoff(nowMs)
        db.coverageDao().deleteEndedBefore(cut)
        return db.glucoseReadingDao().deleteBefore(cut) + db.treatmentDao().deleteBefore(cut) + db.iobDao().deleteBefore(cut)
    }
}
