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

    @Query("SELECT * FROM treatments WHERE valid = 1 AND timestampMs >= :fromMs ORDER BY timestampMs")
    fun observeValidSince(fromMs: Long): Flow<List<TreatmentEntity>>

    @Query("SELECT * FROM treatments WHERE valid = 1 AND timestampMs >= :fromMs AND timestampMs < :toMs ORDER BY timestampMs")
    suspend fun validBetween(fromMs: Long, toMs: Long): List<TreatmentEntity>

    /** Profile switches and the effective-profile notes AAPS writes with them, all history (a few per change). */
    @Query("SELECT * FROM treatments WHERE valid = 1 AND (eventType = 'Profile Switch' OR (eventType = 'Note' AND rawJson LIKE '%profileJson%')) ORDER BY timestampMs")
    fun observeProfileEvents(): Flow<List<TreatmentEntity>>

    @Query("SELECT * FROM treatments WHERE valid = 1 AND (eventType = 'Profile Switch' OR (eventType = 'Note' AND rawJson LIKE '%profileJson%')) ORDER BY timestampMs")
    suspend fun profileEvents(): List<TreatmentEntity>
}
