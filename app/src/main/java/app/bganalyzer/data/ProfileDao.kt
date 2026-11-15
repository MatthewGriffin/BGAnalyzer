package app.bganalyzer.data

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert

@Dao
interface ProfileDao {
    @Upsert
    suspend fun upsertAll(profiles: List<ProfileEntity>)

    @Query("SELECT * FROM profiles ORDER BY startMs")
    suspend fun all(): List<ProfileEntity>

    @Query("SELECT * FROM profiles ORDER BY startMs DESC LIMIT 1")
    suspend fun latest(): ProfileEntity?
}
