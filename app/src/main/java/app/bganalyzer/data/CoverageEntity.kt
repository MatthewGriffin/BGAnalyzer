package app.bganalyzer.data

import androidx.room.Entity

/**
 * A stretch of time that has been asked for from Nightscout for one kind of data ([source]), meaning records
 * after [startMs] up to and including [endMs]. Merged so the rows for a source never overlap.
 * It can be rebuilt (glucose from the stored readings, the rest by asking again), so it is not in the backup.
 */
@Entity(tableName = "sync_coverage", primaryKeys = ["source", "startMs"])
data class CoverageEntity(val source: String, val startMs: Long, val endMs: Long)
