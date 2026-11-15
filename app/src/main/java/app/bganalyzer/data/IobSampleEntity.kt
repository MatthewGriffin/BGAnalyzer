package app.bganalyzer.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Insulin on board (and carbs on board) as reported by the loop in a Nightscout device status.
 * Keyed by the document id, not the time, because two uploaders can report the same moment.
 */
@Entity(tableName = "iob_samples", indices = [Index("timestampMs")])
data class IobSampleEntity(
    @PrimaryKey val id: String,
    val timestampMs: Long,
    val iob: Double?,
    val basalIob: Double?,
    val activity: Double?,
    val cob: Double?,
)
