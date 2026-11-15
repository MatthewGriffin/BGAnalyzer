package app.bganalyzer.sync

import app.bganalyzer.data.GlucoseReadingEntity
import org.bson.Document
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class GlucoseEntryMapperTest {
    @Test
    fun normalEntryIsMapped() {
        val doc = Document("type", "sgv").append("sgv", 120).append("date", 1_790_000_000_000L).append("direction", "Flat")
        assertEquals(GlucoseReadingEntity(1_790_000_000_000L, 120.0), GlucoseEntryMapper.fromDocument(doc))
    }

    @Test
    fun entryWithoutTypeIsStillUsed() {
        assertEquals(110.0, GlucoseEntryMapper.fromDocument(Document("sgv", 110.5 - 0.5).append("date", 5L))!!.mgdl, 0.0)
    }

    @Test
    fun otherTypesAndBadValuesAreSkipped() {
        assertNull(GlucoseEntryMapper.fromDocument(Document("type", "cal").append("sgv", 120).append("date", 5L)))
        assertNull(GlucoseEntryMapper.fromDocument(Document("type", "sgv").append("date", 5L)))
        assertNull(GlucoseEntryMapper.fromDocument(Document("sgv", 10).append("date", 5L)))
        assertNull(GlucoseEntryMapper.fromDocument(Document("sgv", 900).append("date", 5L)))
        assertNull(GlucoseEntryMapper.fromDocument(Document("sgv", "120").append("date", 5L)))
        assertNull(GlucoseEntryMapper.fromDocument(Document("sgv", 120)))
    }
}
