package app.bganalyzer.data

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

/**
 * A day the user marked as bad data for analysis, for example when a pump failed and insulin pens were used.
 * [date] is the local calendar date, ISO format (2026-11-15). User-entered, so it is part of the backup.
 */
@Entity(tableName = "excluded_days")
data class ExcludedDayEntity(
    @PrimaryKey val date: String,
    val note: String,
    val createdMs: Long,
)

@Dao
interface ExcludedDayDao {
    @Query("SELECT * FROM excluded_days ORDER BY date DESC")
    fun observeAll(): Flow<List<ExcludedDayEntity>>

    @Query("SELECT * FROM excluded_days ORDER BY date")
    suspend fun all(): List<ExcludedDayEntity>

    @Upsert
    suspend fun upsertAll(rows: List<ExcludedDayEntity>)

    @Query("DELETE FROM excluded_days WHERE date = :date")
    suspend fun delete(date: String)
}
