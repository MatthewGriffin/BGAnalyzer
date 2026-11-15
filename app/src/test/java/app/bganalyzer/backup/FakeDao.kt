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
    override suspend fun timestampsSince(fromMs: Long) = rows.keys.filter { it >= fromMs }
    override suspend fun between(fromMs: Long, toMs: Long) = rows.values.filter { it.timestampMs in fromMs until toMs }
    override fun observeSince(fromMs: Long): Flow<List<GlucoseReadingEntity>> = flowOf(rows.values.filter { it.timestampMs >= fromMs })
}

class FakeTreatmentDao(initial: List<app.bganalyzer.data.TreatmentEntity> = emptyList()) : app.bganalyzer.data.TreatmentDao {
    val rows = initial.associateBy { it.id }.toMutableMap()
    override suspend fun upsertAll(treatments: List<app.bganalyzer.data.TreatmentEntity>) { treatments.forEach { rows[it.id] = it } }
    override suspend fun all() = rows.values.sortedBy { it.timestampMs }
    override fun observeCount(): Flow<Int> = flowOf(rows.size)
    override suspend fun newestTimestamp() = rows.values.maxOfOrNull { it.timestampMs }
    override suspend fun newestServerModified() = rows.values.mapNotNull { it.srvModifiedMs }.maxOrNull()
    override suspend fun validBetween(fromMs: Long, toMs: Long) = all().filter { it.valid && it.timestampMs in fromMs until toMs }
    override fun observeValidSince(fromMs: Long): Flow<List<app.bganalyzer.data.TreatmentEntity>> = flowOf(rows.values.filter { it.valid && it.timestampMs >= fromMs })
}

class FakeProfileDao(initial: List<app.bganalyzer.data.ProfileEntity> = emptyList()) : app.bganalyzer.data.ProfileDao {
    val rows = initial.associateBy { it.id }.toMutableMap()
    override suspend fun upsertAll(profiles: List<app.bganalyzer.data.ProfileEntity>) { profiles.forEach { rows[it.id] = it } }
    override suspend fun all() = rows.values.sortedBy { it.startMs }
    override suspend fun latest() = rows.values.maxByOrNull { it.startMs }
}

class FakeIobDao(initial: List<app.bganalyzer.data.IobSampleEntity> = emptyList()) : app.bganalyzer.data.IobDao {
    val rows = initial.associateBy { it.id }.toMutableMap()
    override suspend fun upsertAll(samples: List<app.bganalyzer.data.IobSampleEntity>) { samples.forEach { rows[it.id] = it } }
    override suspend fun all() = rows.values.sortedBy { it.timestampMs }
    override fun observeSince(fromMs: Long): Flow<List<app.bganalyzer.data.IobSampleEntity>> = flowOf(all2().filter { it.timestampMs >= fromMs })
    override suspend fun timestampsSince(fromMs: Long) = all2().filter { it.timestampMs >= fromMs }.map { it.timestampMs }
    private fun all2() = rows.values.sortedBy { it.timestampMs }
}

class FakeSettings(override var uri: String = "", override var database: String = "") : ConnectionSettings
