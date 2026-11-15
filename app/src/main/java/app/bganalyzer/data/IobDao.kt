package app.bganalyzer.data

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface IobDao {
    @Upsert
    suspend fun upsertAll(samples: List<IobSampleEntity>)

    @Query("SELECT * FROM iob_samples ORDER BY timestampMs")
    suspend fun all(): List<IobSampleEntity>

    @Query("SELECT * FROM iob_samples WHERE timestampMs >= :fromMs ORDER BY timestampMs")
    fun observeSince(fromMs: Long): Flow<List<IobSampleEntity>>

    @Query("SELECT timestampMs FROM iob_samples WHERE timestampMs >= :fromMs ORDER BY timestampMs")
    suspend fun timestampsSince(fromMs: Long): List<Long>
}
