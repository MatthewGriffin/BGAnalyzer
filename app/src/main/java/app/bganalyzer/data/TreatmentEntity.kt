package app.bganalyzer.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * One Nightscout treatment record (bolus, carbs, temp basal, profile switch and so on).
 * The fields analysis needs are columns; [rawJson] keeps the whole original document so later features
 * (autotune, delivery checks) can read more without another database migration.
 * Records marked invalid in Nightscout are kept with [valid] false and left out of analysis.
 */
@Entity(tableName = "treatments", indices = [Index("timestampMs")])
data class TreatmentEntity(
    @PrimaryKey val id: String,
    val timestampMs: Long,
    val eventType: String?,
    val insulin: Double?,
    /** Carbs live on bolus records, not only on carb records. */
    val carbs: Double?,
    val isSmb: Boolean,
    val rateUph: Double?,
    val durationMs: Long?,
    val percentage: Double?,
    val valid: Boolean,
    val srvModifiedMs: Long?,
    val rawJson: String,
)
