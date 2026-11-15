package app.bganalyzer.backup

import app.bganalyzer.data.GlucoseReadingDao
import app.bganalyzer.data.GlucoseReadingEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf

/** In-memory stand-in for the Room DAO. Upsert replaces by timestamp, like the real one. */
class FakeDao(initial: List<GlucoseReadingEntity> = emptyList()) : GlucoseReadingDao {
    val rows = initial.associateBy { it.timestampMs }.toSortedMap()

    override suspend fun upsertAll(readings: List<GlucoseReadingEntity>) { readings.forEach { rows[it.timestampMs] = it } }
    override fun observeCount(): Flow<Int> = flowOf(rows.size)
    override suspend fun all() = rows.values.toList()
    override suspend fun newestTimestamp() = rows.keys.maxOrNull()
    override suspend fun between(fromMs: Long, toMs: Long) = rows.values.filter { it.timestampMs in fromMs until toMs }
    override fun observeSince(fromMs: Long): Flow<List<GlucoseReadingEntity>> = flowOf(rows.values.filter { it.timestampMs >= fromMs })
}

class FakeSettings(override var uri: String = "", override var database: String = "") : ConnectionSettings
