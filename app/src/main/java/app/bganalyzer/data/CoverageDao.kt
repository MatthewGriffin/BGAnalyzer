package app.bganalyzer.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface CoverageDao {
    @Query("SELECT * FROM sync_coverage WHERE source = :source ORDER BY startMs")
    suspend fun forSource(source: String): List<CoverageEntity>

    @Query("SELECT * FROM sync_coverage ORDER BY source, startMs")
    fun observeAll(): Flow<List<CoverageEntity>>

    @Query("DELETE FROM sync_coverage WHERE source = :source")
    suspend fun clear(source: String)

    @Insert
    suspend fun insertAll(rows: List<CoverageEntity>)
}
