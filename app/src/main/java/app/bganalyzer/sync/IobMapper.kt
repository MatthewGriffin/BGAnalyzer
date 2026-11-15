package app.bganalyzer.sync

import app.bganalyzer.data.IobSampleEntity
import org.bson.Document
import org.bson.types.ObjectId
import java.time.Instant

/** Reads the insulin and carbs on board out of a Nightscout `devicestatus` document written by the loop. */
object IobMapper {
    /** Null for documents without loop data (uploader battery and pump status) or without a usable time. */
    fun fromDocument(doc: Document): IobSampleEntity? {
        val id = when (val v = doc["_id"]) { is ObjectId -> v.toHexString(); is String -> v.takeIf { it.isNotBlank() }; else -> null } ?: return null
        val openaps = doc["openaps"] as? Document ?: return null
        val iobDoc = openaps["iob"] as? Document
        val cob = ((openaps["suggested"] as? Document)?.get("COB") as? Number)?.toDouble()
        val iob = (iobDoc?.get("iob") as? Number)?.toDouble()
        if (iob == null && cob == null) return null
        // The loop's own time is when the value applies; fall back to when the record was created.
        val time = listOf(iobDoc?.get("time"), doc["created_at"]).firstNotNullOfOrNull { t ->
            (t as? String)?.let { runCatching { Instant.parse(it).toEpochMilli() }.getOrNull() }
        } ?: return null
        return IobSampleEntity(
            id = id,
            timestampMs = time,
            iob = iob,
            basalIob = (iobDoc?.get("basaliob") as? Number)?.toDouble(),
            activity = (iobDoc?.get("activity") as? Number)?.toDouble(),
            cob = cob,
        )
    }
}
