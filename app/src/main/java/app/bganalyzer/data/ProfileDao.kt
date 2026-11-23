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

    @Query("SELECT timezone FROM profiles ORDER BY startMs DESC LIMIT 50")
    suspend fun recentTimezones(): List<String?>

    @Query("SELECT * FROM profiles ORDER BY startMs DESC LIMIT 1")
    suspend fun latest(): ProfileEntity?
}

/** The zone days and hours are cut in; see [app.bganalyzer.domain.ZoneResolver]. */
suspend fun ProfileDao.zone(): java.time.ZoneId = app.bganalyzer.domain.ZoneResolver.resolve(recentTimezones())
