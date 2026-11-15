package app.bganalyzer.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/** One CGM reading. The value is always mg/dL; the time is epoch milliseconds (UTC). */
@Entity(tableName = "glucose_readings")
data class GlucoseReadingEntity(
    @PrimaryKey val timestampMs: Long,
    val mgdl: Double,
)
