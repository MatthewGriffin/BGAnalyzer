package app.bganalyzer.sync

import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import org.bson.Document
import org.bson.json.JsonMode
import org.bson.json.JsonWriterSettings
import org.bson.types.ObjectId
import java.time.Instant

/** Turns Nightscout `treatments` and `profile` documents into stored rows. Pure, so it is tested without a database. */
object TreatmentMapper {
    private val json = JsonWriterSettings.builder().outputMode(JsonMode.RELAXED).build()

    /** The document id as text, whether Nightscout stored an ObjectId or a string. */
    private fun idOf(doc: Document): String? = when (val id = doc["_id"]) {
        is ObjectId -> id.toHexString()
        is String -> id.takeIf { it.isNotBlank() }
        else -> null
    }

    /** Event time: the numeric `date`, or the ISO `created_at` when that is missing. Null if neither is usable. */
    private fun timeOf(doc: Document, vararg isoFields: String): Long? {
        (doc["date"] as? Number)?.toLong()?.takeIf { it > 0 }?.let { return it }
        for (f in isoFields) {
            val text = doc[f] as? String ?: continue
            runCatching { Instant.parse(text).toEpochMilli() }.getOrNull()?.let { return it }
        }
        return null
    }

    private fun num(doc: Document, key: String) = (doc[key] as? Number)?.toDouble()

    /** Returns null for a record that has no id or no usable time. Invalid records are kept, marked not valid. */
    fun treatment(doc: Document): TreatmentEntity? {
        val id = idOf(doc) ?: return null
        val time = timeOf(doc, "created_at") ?: return null
        val durationMs = (doc["durationInMilliseconds"] as? Number)?.toLong()
            ?: num(doc, "duration")?.let { (it * 60_000).toLong() }
        return TreatmentEntity(
            id = id,
            timestampMs = time,
            eventType = doc["eventType"] as? String,
            insulin = num(doc, "insulin"),
            carbs = num(doc, "carbs"),
            isSmb = doc["isSMB"] == true,
            rateUph = num(doc, "absolute") ?: num(doc, "rate"),
            durationMs = durationMs?.takeIf { it >= 0 },
            percentage = num(doc, "percent") ?: num(doc, "percentage"),
            valid = doc["isValid"] != false,
            srvModifiedMs = (doc["srvModified"] as? Number)?.toLong(),
            rawJson = doc.toJson(json),
        )
    }

    /** Reads units and timezone from the default profile, falling back to the first profile in the store. */
    fun profile(doc: Document): ProfileEntity? {
        val id = idOf(doc) ?: return null
        val start = timeOf(doc, "startDate", "created_at") ?: return null
        val default = doc["defaultProfile"] as? String
        val store = doc["store"] as? Document
        val main = (default?.let { store?.get(it) } ?: store?.values?.firstOrNull()) as? Document
        return ProfileEntity(
            id = id,
            startMs = start,
            defaultProfile = default,
            units = (main?.get("units") as? String) ?: (doc["units"] as? String),
            timezone = main?.get("timezone") as? String,
            rawJson = doc.toJson(json),
        )
    }
}
