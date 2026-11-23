package app.bganalyzer.sync

import androidx.room.withTransaction
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.data.CoverageEntity
import app.bganalyzer.mongo.NightscoutMongo
import org.bson.Document

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
    }

    /** Blocks, so call it off the main thread. [days] is the period to make complete. [onProgress] gets the running number of stored records. */
    suspend fun run(uri: String, database: String, days: Int, onProgress: (Int) -> Unit = {}, deepGapCheck: Boolean = false): SyncResult =
        MongoSyncSource(NightscoutMongo.open(uri), database).use { run(it, days, onProgress, deepGapCheck) }

    /** The same sync from any [source] (MongoDB or the REST API). The source is not closed here. */
    suspend fun run(source: SyncSource, days: Int, onProgress: (Int) -> Unit = {}, deepGapCheck: Boolean = false): SyncResult {
        val now = nowMs()
        val period = SyncPlanner.period(now, days)
        Sources.LEGACY.forEach { db.coverageDao().clear(it) }
        seedGlucoseCoverage()
        var stored = 0
        val progress = { n: Int -> stored += n; onProgress(stored) }
        val glucose = glucose(source, period, now, progress, deepGapCheck)
        val treatments = treatments(source, period, now, progress)
        val iob = iob(source, period, now, progress, deepGapCheck)
        val profiles = profiles(source)
        return SyncResult(glucose.fetched, treatments.fetched, profiles, iob.fetched, glucose.spans + treatments.spans + iob.spans)
    }

    private fun lookback(deep: Boolean, period: Span, now: Long) = if (deep) now - period.startMs else SyncPlanner.RECHECK_RECENT_MS

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

    private suspend fun glucose(source: SyncSource, period: Span, now: Long, progress: (Int) -> Unit, deep: Boolean): Part {
        val dao = db.glucoseReadingDao()
        val covered = db.coverageDao().forSource(GLUCOSE).map { Span(it.startMs, it.endMs) }
        val holes = SyncPlanner.recentGaps(dao.timestampsSince(period.startMs), period, now, SyncPlanner.GLUCOSE_GAP_MS, lookback(deep, period, now))
        val spans = SyncPlanner.spans(period, covered, holes, SyncPlanner.GLUCOSE_TAIL_MS, now)
        var fetched = 0
        for (chunk in SyncPlanner.chunks(spans)) {
            fetched += batched(source.glucose(chunk), GlucoseEntryMapper::fromDocument, { dao.upsertAll(it) }, progress)
            markCovered(GLUCOSE, chunk)
        }
        return Part(fetched, spans.size)
    }

    private suspend fun treatments(source: SyncSource, period: Span, now: Long, progress: (Int) -> Unit): Part {
        val dao = db.treatmentDao()
        val covered = db.coverageDao().forSource(TREATMENTS).map { Span(it.startMs, it.endMs) }
        val spans = SyncPlanner.spans(period, covered, emptyList(), SyncPlanner.TREATMENT_TAIL_MS, now)
        // Also pick up records edited or invalidated since the last sync (newer records carry srvModified).
        val edited: Long? = dao.newestServerModified()
        var fetched = 0
        for ((i, chunk) in SyncPlanner.chunks(spans).withIndex()) {
            fetched += batched(source.treatments(chunk, if (i == 0) edited else null), TreatmentMapper::treatment, { dao.upsertAll(it) }, progress)
            markCovered(TREATMENTS, chunk)
        }
        fetched += profileInForceAtStart(source, period)
        return Part(fetched, spans.size)
    }

    /**
     * The profile active at the start of the period was set by a switch before it, which the period's own requests
     * do not reach. If none is stored from before the period, ask for the latest switch and its effective records.
     */
    private suspend fun profileInForceAtStart(source: SyncSource, period: Span): Int {
        val dao = db.treatmentDao()
        if (dao.profileEvents().any { it.timestampMs <= period.startMs }) return 0
        return batched(source.profileEventsBefore(period.startMs), TreatmentMapper::treatment, { dao.upsertAll(it) }, {})
    }

    private suspend fun iob(source: SyncSource, period: Span, now: Long, progress: (Int) -> Unit, deep: Boolean): Part {
        val dao = db.iobDao()
        val covered = db.coverageDao().forSource(IOB).map { Span(it.startMs, it.endMs) }
        val holes = SyncPlanner.recentGaps(dao.timestampsSince(period.startMs), period, now, SyncPlanner.IOB_GAP_MS, lookback(deep, period, now))
        val spans = SyncPlanner.spans(period, covered, holes, SyncPlanner.IOB_TAIL_MS, now)
        var fetched = 0
        for (chunk in SyncPlanner.chunks(spans)) {
            fetched += batched(source.iob(chunk), IobMapper::fromDocument, { dao.upsertAll(it) }, progress)
            markCovered(IOB, chunk)
        }
        return Part(fetched, spans.size)
    }

    /** Profiles are few and rarely change: with some stored, ask only for newer ones (a day of overlap). */
    private suspend fun profiles(source: SyncSource): Int {
        val dao = db.profileDao()
        val newest = dao.latest()?.startMs
        return batched(source.profiles(newest), TreatmentMapper::profile, { dao.upsertAll(it) }, {})
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
        find: DocCursor,
        map: (Document) -> T?,
        store: suspend (List<T>) -> Unit,
        stored: (Int) -> Unit,
    ): Int {
        var fetched = 0
        val batch = ArrayList<T>(BATCH)
        find.use { cursor ->
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
