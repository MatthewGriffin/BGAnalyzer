package app.bganalyzer.data

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface GlucoseReadingDao {
    @Upsert
    suspend fun upsertAll(readings: List<GlucoseReadingEntity>)

    @Query("SELECT COUNT(*) FROM glucose_readings")
    fun observeCount(): Flow<Int>

    @Query("SELECT MAX(timestampMs) FROM glucose_readings")
    suspend fun newestTimestamp(): Long?

    @Query("SELECT * FROM glucose_readings WHERE timestampMs >= :fromMs AND timestampMs < :toMs ORDER BY timestampMs")
    suspend fun between(fromMs: Long, toMs: Long): List<GlucoseReadingEntity>

    @Query("SELECT * FROM glucose_readings WHERE timestampMs >= :fromMs ORDER BY timestampMs")
    fun observeSince(fromMs: Long): Flow<List<GlucoseReadingEntity>>
}
