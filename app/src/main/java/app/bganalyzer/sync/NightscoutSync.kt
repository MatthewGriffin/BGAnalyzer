package app.bganalyzer.sync

import app.bganalyzer.data.AppDatabase
import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import app.bganalyzer.mongo.NightscoutMongo
import com.mongodb.client.MongoDatabase
import com.mongodb.client.model.Filters
import com.mongodb.client.model.Projections
import com.mongodb.client.model.Sorts
import org.bson.Document

data class SyncResult(val glucoseFetched: Int, val treatmentsFetched: Int, val profilesFetched: Int)

/** Copies glucose, treatments and profiles from the Nightscout MongoDB into the local database. Read-only on the Nightscout side. */
class NightscoutSync(private val db: AppDatabase, private val nowMs: () -> Long = System::currentTimeMillis) {
    private companion object {
        const val BATCH = 1000
        /** Profile uploads are frequent (hundreds over a few months); the newest are enough. */
        const val MAX_PROFILES = 300
    }

    /** Blocks, so call it off the main thread. [onProgress] gets the running number of stored records. */
    suspend fun run(uri: String, database: String, onProgress: (Int) -> Unit = {}): SyncResult =
        NightscoutMongo.open(uri).use { client ->
            val mongo = client.getDatabase(database)
            var stored = 0
            val glucose = glucose(mongo) { stored += it; onProgress(stored) }
            val treatments = treatments(mongo) { stored += it; onProgress(stored) }
            val profiles = profiles(mongo)
            SyncResult(glucose, treatments, profiles)
        }

    private suspend fun glucose(mongo: MongoDatabase, stored: (Int) -> Unit): Int {
        val dao = db.glucoseReadingDao()
        val after = SyncPlan.fetchAfter(dao.newestTimestamp(), nowMs())
        return batched(
            mongo.getCollection("entries")
                .find(Filters.and(Filters.gt("date", after), Filters.exists("sgv")))
                .projection(Projections.include("sgv", "date", "type"))
                .sort(Sorts.ascending("date")),
            GlucoseEntryMapper::fromDocument,
            { rows: List<GlucoseReadingEntity> -> dao.upsertAll(rows) },
            stored,
        )
    }

    private suspend fun treatments(mongo: MongoDatabase, stored: (Int) -> Unit): Int {
        val dao = db.treatmentDao()
        val createdAfter = SyncPlan.treatmentsCreatedAfterIso(dao.newestTimestamp(), nowMs())
        // Also pick up older records that were edited or invalidated since the last sync (newer records carry srvModified).
        val modifiedAfter = dao.newestServerModified()
        val filter = if (modifiedAfter == null) Filters.gt("created_at", createdAfter)
        else Filters.or(Filters.gt("created_at", createdAfter), Filters.gt("srvModified", modifiedAfter))
        return batched(
            mongo.getCollection("treatments").find(filter),
            TreatmentMapper::treatment,
            { rows: List<TreatmentEntity> -> dao.upsertAll(rows) },
            stored,
        )
    }

    private suspend fun profiles(mongo: MongoDatabase): Int {
        val dao = db.profileDao()
        return batched(
            mongo.getCollection("profile").find().sort(Sorts.descending("created_at")).limit(MAX_PROFILES),
            TreatmentMapper::profile,
            { rows: List<ProfileEntity> -> dao.upsertAll(rows) },
            {},
        )
    }

    /** Reads a cursor in batches, maps each document, and stores each batch. Returns how many documents were read. */
    private suspend fun <T> batched(
        find: com.mongodb.client.FindIterable<Document>,
        map: (Document) -> T?,
        store: suspend (List<T>) -> Unit,
        stored: (Int) -> Unit,
    ): Int {
        var fetched = 0
        val batch = ArrayList<T>(BATCH)
        find.batchSize(BATCH).iterator().use { cursor ->
            while (cursor.hasNext()) {
                fetched++
                map(cursor.next())?.let(batch::add)
                if (batch.size == BATCH) { store(batch.toList()); stored(batch.size); batch.clear() }
            }
        }
        if (batch.isNotEmpty()) { store(batch.toList()); stored(batch.size) }
        return fetched
    }
}
