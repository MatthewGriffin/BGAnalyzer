package app.bganalyzer.sync

import androidx.room.withTransaction
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.data.CoverageEntity
import app.bganalyzer.mongo.NightscoutMongo
import com.mongodb.client.FindIterable
import com.mongodb.client.MongoDatabase
import com.mongodb.client.model.Filters
import com.mongodb.client.model.Projections
import com.mongodb.client.model.Sorts
import org.bson.Document
import org.bson.conversions.Bson

/** What a sync asked for and read. [spans] is how many separate stretches of time were requested. */
data class SyncResult(
    val glucoseFetched: Int,
    val treatmentsFetched: Int,
    val profilesFetched: Int,
    val iobFetched: Int,
    val spans: Int,
)

/**
 * Copies glucose, treatments, insulin on board and profiles from the Nightscout MongoDB into the local database,
 * asking only for what is missing in the chosen period (see [SyncPlanner]). Read-only on the Nightscout side.
 */
class NightscoutSync(private val db: AppDatabase, private val nowMs: () -> Long = System::currentTimeMillis) {
    private companion object {
        const val BATCH = 1000
        const val GLUCOSE = Sources.GLUCOSE
        const val TREATMENTS = Sources.TREATMENTS
        const val IOB = Sources.IOB
        /** With nothing stored, take the newest profiles; they are few and small. */
        const val MAX_FIRST_PROFILES = 300
    }

    /** Blocks, so call it off the main thread. [days] is the period to make complete. [onProgress] gets the running number of stored records. */
    suspend fun run(uri: String, database: String, days: Int, onProgress: (Int) -> Unit = {}): SyncResult {
        val now = nowMs()
        val period = SyncPlanner.period(now, days)
        Sources.LEGACY.forEach { db.coverageDao().clear(it) }
        seedGlucoseCoverage()
        return NightscoutMongo.open(uri).use { client ->
            val mongo = client.getDatabase(database)
            var stored = 0
            val progress = { n: Int -> stored += n; onProgress(stored) }
            val glucose = glucose(mongo, period, now, progress)
            val treatments = treatments(mongo, period, now, progress)
            val iob = iob(mongo, period, now, progress)
            val profiles = profiles(mongo)
            SyncResult(glucose.fetched, treatments.fetched, profiles, iob.fetched, glucose.spans + treatments.spans + iob.spans)
        }
    }

    private class Part(val fetched: Int, val spans: Int)

    /**
     * Readings stored before coverage was tracked have no coverage rows. Treat unbroken stretches of readings as
     * checked, so only the holes between them are asked for (once), not the whole history.
     */
    private suspend fun seedGlucoseCoverage() {
        if (db.coverageDao().forSource(GLUCOSE).isNotEmpty()) return
        val stamps = db.glucoseReadingDao().timestampsSince(0)
        if (stamps.isEmpty()) return
        replaceCoverage(GLUCOSE, SyncPlanner.coverageFromRuns(stamps, SyncPlanner.GLUCOSE_GAP_MS))
    }

    private suspend fun glucose(mongo: MongoDatabase, period: Span, now: Long, progress: (Int) -> Unit): Part {
        val dao = db.glucoseReadingDao()
        val covered = db.coverageDao().forSource(GLUCOSE).map { Span(it.startMs, it.endMs) }
        val holes = SyncPlanner.recentGaps(dao.timestampsSince(period.startMs), period, now, SyncPlanner.GLUCOSE_GAP_MS)
        val spans = SyncPlanner.spans(period, covered, holes, SyncPlanner.GLUCOSE_TAIL_MS, now)
        var fetched = 0
        for (chunk in SyncPlanner.chunks(spans)) {
            val filter = Filters.and(Filters.exists("sgv"), Filters.or(chunk.map { Filters.and(Filters.gt("date", it.startMs), Filters.lte("date", it.endMs)) }))
            fetched += batched(
                mongo.getCollection("entries").find(filter).projection(Projections.include("sgv", "date", "type")),
                GlucoseEntryMapper::fromDocument, { dao.upsertAll(it) }, progress,
            )
            markCovered(GLUCOSE, chunk)
        }
        return Part(fetched, spans.size)
    }

    private suspend fun treatments(mongo: MongoDatabase, period: Span, now: Long, progress: (Int) -> Unit): Part {
        val dao = db.treatmentDao()
        val covered = db.coverageDao().forSource(TREATMENTS).map { Span(it.startMs, it.endMs) }
        val spans = SyncPlanner.spans(period, covered, emptyList(), SyncPlanner.TREATMENT_TAIL_MS, now)
        // Also pick up records edited or invalidated since the last sync (newer records carry srvModified).
        val edited: Bson? = dao.newestServerModified()?.let { Filters.gt("srvModified", it) }
        var fetched = 0
        for ((i, chunk) in SyncPlanner.chunks(spans).withIndex()) {
            val ranges = eventTimeRanges(chunk)
            val filter = if (i == 0 && edited != null) Filters.or(ranges + edited) else Filters.or(ranges)
            fetched += batched(mongo.getCollection("treatments").find(filter), TreatmentMapper::treatment, { dao.upsertAll(it) }, progress)
            markCovered(TREATMENTS, chunk)
        }
        fetched += profileInForceAtStart(mongo, period)
        return Part(fetched, spans.size)
    }

    /**
     * The profile active at the start of the period was set by a switch before it, which the period's own requests
     * do not reach. If none is stored from before the period, ask for the latest switch and its effective records.
     */
    private suspend fun profileInForceAtStart(mongo: MongoDatabase, period: Span): Int {
        val dao = db.treatmentDao()
        if (dao.profileEvents().any { it.timestampMs <= period.startMs }) return 0
        val filter = Filters.and(
            Filters.lte("date", period.startMs),
            Filters.or(Filters.eq("eventType", "Profile Switch"), Filters.and(Filters.eq("eventType", "Note"), Filters.exists("profileJson"))),
        )
        return batched(
            mongo.getCollection("treatments").find(filter).sort(Sorts.descending("date")).limit(6),
            TreatmentMapper::treatment, { dao.upsertAll(it) }, {},
        )
    }

    private suspend fun iob(mongo: MongoDatabase, period: Span, now: Long, progress: (Int) -> Unit): Part {
        val dao = db.iobDao()
        val covered = db.coverageDao().forSource(IOB).map { Span(it.startMs, it.endMs) }
        val holes = SyncPlanner.recentGaps(dao.timestampsSince(period.startMs), period, now, SyncPlanner.IOB_GAP_MS)
        val spans = SyncPlanner.spans(period, covered, holes, SyncPlanner.IOB_TAIL_MS, now)
        var fetched = 0
        for (chunk in SyncPlanner.chunks(spans)) {
            val ranges = eventTimeRanges(chunk)
            // Only loop records carry IOB; uploader and pump status records are about half of the collection.
            val filter = Filters.and(Filters.exists("openaps.iob"), Filters.or(ranges))
            fetched += batched(
                mongo.getCollection("devicestatus").find(filter).projection(
                    Projections.include("created_at", "openaps.iob.iob", "openaps.iob.basaliob", "openaps.iob.activity", "openaps.iob.time", "openaps.suggested.COB"),
                ),
                IobMapper::fromDocument, { dao.upsertAll(it) }, progress,
            )
            markCovered(IOB, chunk)
        }
        return Part(fetched, spans.size)
    }

    /**
     * A record belongs to a span if either its `created_at` text or its numeric `date` falls in it. Normally they are the
     * same moment, but a record uploaded late can carry the upload time in one and the event time in the other, and asking
     * only by `created_at` would miss it.
     */
    private fun eventTimeRanges(spans: List<Span>): List<Bson> = spans.flatMap {
        listOf(
            Filters.and(Filters.gt("created_at", SyncPlanner.iso(it.startMs)), Filters.lte("created_at", SyncPlanner.iso(it.endMs))),
            Filters.and(Filters.gt("date", it.startMs), Filters.lte("date", it.endMs)),
        )
    }

    /** Profiles are few and rarely change: with some stored, ask only for newer ones (a day of overlap). */
    private suspend fun profiles(mongo: MongoDatabase): Int {
        val dao = db.profileDao()
        val newest = dao.latest()?.startMs
        val collection = mongo.getCollection("profile")
        val find = if (newest == null) collection.find().sort(Sorts.descending("created_at")).limit(MAX_FIRST_PROFILES)
        else collection.find(Filters.gt("created_at", SyncPlanner.iso(newest - SyncPlanner.DAY_MS)))
        return batched(find, TreatmentMapper::profile, { dao.upsertAll(it) }, {})
    }

    /** Records that a stretch has been fully requested. Called only after its records are stored, so an interrupted sync never claims coverage it does not have. */
    private suspend fun markCovered(source: String, spans: List<Span>) {
        val merged = Intervals.merge(db.coverageDao().forSource(source).map { Span(it.startMs, it.endMs) } + spans)
        replaceCoverage(source, merged)
    }

    private suspend fun replaceCoverage(source: String, spans: List<Span>) = db.withTransaction {
        db.coverageDao().clear(source)
        db.coverageDao().insertAll(spans.map { CoverageEntity(source, it.startMs, it.endMs) })
    }

    /** Reads a cursor in batches, maps each document, and stores each batch. Returns how many documents were read. */
    private suspend fun <T> batched(
        find: FindIterable<Document>,
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
