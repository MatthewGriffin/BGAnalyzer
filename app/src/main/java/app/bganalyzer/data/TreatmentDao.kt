package app.bganalyzer.data

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface TreatmentDao {
    @Upsert
    suspend fun upsertAll(treatments: List<TreatmentEntity>)

    @Query("SELECT * FROM treatments ORDER BY timestampMs")
    suspend fun all(): List<TreatmentEntity>

    @Query("SELECT COUNT(*) FROM treatments")
    fun observeCount(): Flow<Int>

    @Query("SELECT MAX(timestampMs) FROM treatments")
    suspend fun newestTimestamp(): Long?

    @Query("SELECT MAX(srvModifiedMs) FROM treatments")
    suspend fun newestServerModified(): Long?

    @Query("SELECT * FROM treatments WHERE valid = 1 AND timestampMs >= :fromMs AND timestampMs < :toMs ORDER BY timestampMs")
    suspend fun validBetween(fromMs: Long, toMs: Long): List<TreatmentEntity>
}
