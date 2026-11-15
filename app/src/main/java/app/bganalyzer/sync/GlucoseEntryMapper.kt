package app.bganalyzer.sync

import app.bganalyzer.data.GlucoseReadingEntity
import org.bson.Document

/** Turns a Nightscout `entries` document into a stored reading, or null when it is not a usable glucose value. */
object GlucoseEntryMapper {
    /** Readings outside this range are sensor errors or placeholders, not glucose values (mg/dL). */
    const val MIN_MGDL = 20.0
    const val MAX_MGDL = 800.0

    fun fromDocument(doc: Document): GlucoseReadingEntity? {
        // Entries of other types (calibrations, raw data) have no usable glucose. Older entries carry no type at all.
        val type = doc["type"] as? String
        if (type != null && type != "sgv") return null
        val sgv = (doc["sgv"] as? Number)?.toDouble() ?: return null
        val date = (doc["date"] as? Number)?.toLong() ?: return null
        if (sgv < MIN_MGDL || sgv > MAX_MGDL || date <= 0) return null
        return GlucoseReadingEntity(timestampMs = date, mgdl = sgv)
    }
}
