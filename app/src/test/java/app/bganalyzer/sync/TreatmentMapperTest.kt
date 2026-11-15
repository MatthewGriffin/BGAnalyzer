package app.bganalyzer.sync

import org.bson.Document
import org.bson.types.ObjectId
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Documents here follow the shapes seen in a real AAPS-to-Nightscout database, with made-up values. */
class TreatmentMapperTest {
    private val oid = ObjectId("65a1b2c3d4e5f60718293a4b")

    @Test
    fun mealBolusCarriesCarbsAndInsulin() {
        val t = TreatmentMapper.treatment(
            Document("_id", oid).append("eventType", "Meal Bolus").append("date", 1_790_000_000_000L)
                .append("created_at", "2026-09-22T11:33:20.000Z").append("insulin", 2.5).append("carbs", 30)
                .append("isSMB", false).append("isValid", true).append("srvModified", 1_790_000_001_000L),
        )!!
        assertEquals("65a1b2c3d4e5f60718293a4b", t.id)
        assertEquals(1_790_000_000_000L, t.timestampMs)
        assertEquals(2.5, t.insulin!!, 0.0); assertEquals(30.0, t.carbs!!, 0.0)
        assertFalse(t.isSmb); assertTrue(t.valid); assertEquals(1_790_000_001_000L, t.srvModifiedMs)
        assertTrue(t.rawJson.contains("Meal Bolus"))
    }

    @Test
    fun smbIsFlagged() {
        assertTrue(TreatmentMapper.treatment(Document("_id", "x").append("date", 5L).append("isSMB", true).append("insulin", 0.3))!!.isSmb)
    }

    @Test
    fun tempBasalReadsRateAndDurationInEitherUnit() {
        val a = TreatmentMapper.treatment(Document("_id", "a").append("date", 5L).append("eventType", "Temp Basal").append("absolute", 1.2).append("rate", 9.9).append("duration", 30).append("durationInMilliseconds", 1_800_000))!!
        assertEquals(1.2, a.rateUph!!, 0.0); assertEquals(1_800_000L, a.durationMs)
        val b = TreatmentMapper.treatment(Document("_id", "b").append("date", 5L).append("rate", 0.0).append("duration", 15))!!
        assertEquals(0.0, b.rateUph!!, 0.0); assertEquals(900_000L, b.durationMs)
    }

    @Test
    fun timeFallsBackToCreatedAt() {
        val t = TreatmentMapper.treatment(Document("_id", "a").append("created_at", "2026-09-22T11:33:20.000Z"))!!
        assertEquals(java.time.Instant.parse("2026-09-22T11:33:20.000Z").toEpochMilli(), t.timestampMs)
    }

    @Test
    fun invalidRecordsAreKeptButMarked() {
        val t = TreatmentMapper.treatment(Document("_id", "a").append("date", 5L).append("isValid", false))!!
        assertFalse(t.valid)
    }

    @Test
    fun recordsWithoutIdOrTimeAreSkipped() {
        assertNull(TreatmentMapper.treatment(Document("date", 5L)))
        assertNull(TreatmentMapper.treatment(Document("_id", "a")))
        assertNull(TreatmentMapper.treatment(Document("_id", "a").append("created_at", "not a date")))
    }

    @Test
    fun profileReadsUnitsAndTimezoneFromTheDefaultProfile() {
        val doc = Document("_id", "p1").append("startDate", "2026-09-22T11:33:20.000Z").append("defaultProfile", "main")
            .append(
                "store",
                Document(
                    "main",
                    Document("units", "mmol").append("timezone", "Europe/London").append("dia", 7)
                        .append("sens", listOf(Document("time", "00:00").append("timeAsSeconds", 0).append("value", 12.1))),
                ),
            )
        val p = TreatmentMapper.profile(doc)!!
        assertEquals("mmol", p.units); assertEquals("Europe/London", p.timezone); assertEquals("main", p.defaultProfile)
        assertNotNull(p.startMs); assertTrue(p.rawJson.contains("12.1"))
    }

    @Test
    fun profileWithoutStoreStillMapsWithUnknownUnits() {
        val p = TreatmentMapper.profile(Document("_id", "p").append("date", 9L))!!
        assertNull(p.units); assertNull(p.timezone)
    }
}
