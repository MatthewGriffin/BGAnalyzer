package app.bganalyzer.sync

import com.mongodb.client.MongoDatabase
import com.mongodb.client.model.Filters
import com.mongodb.client.model.Projections
import com.mongodb.client.model.Sorts
import org.bson.Document
import org.bson.conversions.Bson

/** Documents read lazily, so a big answer is stored in batches instead of held in memory. Closing stops the read. */
interface DocCursor : Iterator<Document>, AutoCloseable

/**
 * Where a sync reads Nightscout data from: the MongoDB database directly, or the Nightscout REST API. Both give
 * the same documents, so the mappers and the planning are shared. Read-only. Calls block, so use off the main thread.
 * Every `spans` argument is a list of (start, end] stretches of time in epoch milliseconds.
 */
interface SyncSource : AutoCloseable {
    /** Glucose entries (`sgv`) with `date` inside any of [spans]. */
    fun glucose(spans: List<Span>): DocCursor
    /** Treatments whose `created_at` or `date` is inside any of [spans], plus those with `srvModified` after [editedAfterMs]. */
    fun treatments(spans: List<Span>, editedAfterMs: Long?): DocCursor
    /** The newest profile switches and effective-profile notes at or before [beforeMs]. */
    fun profileEventsBefore(beforeMs: Long): DocCursor
    /** Loop status records (with `openaps.iob`) inside any of [spans]. */
    fun iob(spans: List<Span>): DocCursor
    /** Uploaded profile documents, newest first. With [newestStartMs] only those created after it (a day of overlap) are needed. */
    fun profiles(newestStartMs: Long?): DocCursor
}

/** Wraps a list as a cursor. */
internal class ListCursor(private val items: Iterator<Document>) : DocCursor {
    override fun hasNext() = items.hasNext()
    override fun next() = items.next()
    override fun close() {}
}

/** The MongoDB source: the queries the sync has always used. */
class MongoSyncSource(private val client: com.mongodb.client.MongoClient, databaseName: String) : SyncSource {
    private val mongo: MongoDatabase = client.getDatabase(databaseName)

    private class MongoDocCursor(private val cursor: com.mongodb.client.MongoCursor<Document>) : DocCursor {
        override fun hasNext() = cursor.hasNext()
        override fun next(): Document = cursor.next()
        override fun close() = cursor.close()
    }

    private fun com.mongodb.client.FindIterable<Document>.docs(): DocCursor = MongoDocCursor(batchSize(BATCH).iterator())

    override fun glucose(spans: List<Span>): DocCursor {
        val filter = Filters.and(Filters.exists("sgv"), Filters.or(spans.map { Filters.and(Filters.gt("date", it.startMs), Filters.lte("date", it.endMs)) }))
        return mongo.getCollection("entries").find(filter).projection(Projections.include("sgv", "date", "type")).docs()
    }

    override fun treatments(spans: List<Span>, editedAfterMs: Long?): DocCursor {
        val ranges = eventTimeRanges(spans)
        val edited: Bson? = editedAfterMs?.let { Filters.gt("srvModified", it) }
        val filter = if (edited != null) Filters.or(ranges + edited) else Filters.or(ranges)
        return mongo.getCollection("treatments").find(filter).docs()
    }

    override fun profileEventsBefore(beforeMs: Long): DocCursor {
        val filter = Filters.and(
            Filters.lte("date", beforeMs),
            Filters.or(Filters.eq("eventType", "Profile Switch"), Filters.and(Filters.eq("eventType", "Note"), Filters.exists("profileJson"))),
        )
        return mongo.getCollection("treatments").find(filter).sort(Sorts.descending("date")).limit(6).docs()
    }

    override fun iob(spans: List<Span>): DocCursor {
        // Only loop records carry IOB; uploader and pump status records are about half of the collection.
        val filter = Filters.and(Filters.exists("openaps.iob"), Filters.or(eventTimeRanges(spans)))
        return mongo.getCollection("devicestatus").find(filter).projection(
            Projections.include("created_at", "openaps.iob.iob", "openaps.iob.basaliob", "openaps.iob.activity", "openaps.iob.time", "openaps.suggested.COB"),
        ).docs()
    }

    override fun profiles(newestStartMs: Long?): DocCursor {
        val collection = mongo.getCollection("profile")
        val find = if (newestStartMs == null) collection.find().sort(Sorts.descending("created_at")).limit(MAX_FIRST_PROFILES)
        else collection.find(Filters.gt("created_at", SyncPlanner.iso(newestStartMs - SyncPlanner.DAY_MS)))
        return find.docs()
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

    override fun close() = client.close()

    private companion object {
        const val BATCH = 1000
        /** With nothing stored, take the newest profiles; they are few and small. */
        const val MAX_FIRST_PROFILES = 300
    }
}
