package app.bganalyzer.sync

import app.bganalyzer.data.GlucoseReadingDao
import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.mongo.NightscoutMongo
import com.mongodb.client.model.Filters
import com.mongodb.client.model.Projections
import com.mongodb.client.model.Sorts

/** Result of one sync run. */
data class SyncResult(val fetched: Int, val stored: Int)

/** Copies glucose readings from the Nightscout database into the local database. Read-only on the Nightscout side. */
class GlucoseSync(private val dao: GlucoseReadingDao, private val nowMs: () -> Long = System::currentTimeMillis) {
    private companion object {
        const val BATCH = 1000
    }

    /** Blocks, so call it off the main thread. [onProgress] gets the running count of stored readings. */
    suspend fun run(uri: String, database: String, onProgress: (Int) -> Unit = {}): SyncResult {
        val after = SyncPlan.fetchAfter(dao.newestTimestamp(), nowMs())
        var fetched = 0
        var stored = 0
        NightscoutMongo.open(uri).use { client ->
            val cursor = client.getDatabase(database).getCollection("entries")
                .find(Filters.and(Filters.gt("date", after), Filters.exists("sgv")))
                .projection(Projections.include("sgv", "date", "type"))
                .sort(Sorts.ascending("date"))
                .batchSize(BATCH)
                .iterator()
            cursor.use {
                val batch = ArrayList<GlucoseReadingEntity>(BATCH)
                while (it.hasNext()) {
                    fetched++
                    GlucoseEntryMapper.fromDocument(it.next())?.let(batch::add)
                    if (batch.size == BATCH) {
                        dao.upsertAll(batch); stored += batch.size; batch.clear(); onProgress(stored)
                    }
                }
                if (batch.isNotEmpty()) { dao.upsertAll(batch); stored += batch.size; onProgress(stored) }
            }
        }
        return SyncResult(fetched, stored)
    }
}
