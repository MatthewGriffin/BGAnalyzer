package app.bganalyzer.sync

import org.bson.Document
import org.bson.types.ObjectId
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Instant

/** Shapes follow real AAPS loop device statuses, with made-up values. */
class IobMapperTest {
    private val oid = ObjectId("65a1b2c3d4e5f60718293a4b")
    private fun loop(time: String? = "2026-09-22T11:33:20Z", iob: Number? = 1.5, cob: Number? = 20) = Document("_id", oid)
        .append("created_at", "2026-09-22T11:33:30.000Z")
        .append(
            "openaps",
            Document("iob", Document("iob", iob).append("basaliob", 0.25).append("activity", 0.01).also { if (time != null) it.append("time", time) })
                .append("suggested", Document("COB", cob)),
        )

    @Test
    fun loopStatusIsMappedUsingTheLoopsOwnTime() {
        val s = IobMapper.fromDocument(loop())!!
        assertEquals("65a1b2c3d4e5f60718293a4b", s.id)
        assertEquals(Instant.parse("2026-09-22T11:33:20Z").toEpochMilli(), s.timestampMs)
        assertEquals(1.5, s.iob!!, 0.0); assertEquals(0.25, s.basalIob!!, 0.0); assertEquals(0.01, s.activity!!, 0.0); assertEquals(20.0, s.cob!!, 0.0)
    }

    @Test
    fun missingLoopTimeFallsBackToCreatedAt() {
        assertEquals(Instant.parse("2026-09-22T11:33:30.000Z").toEpochMilli(), IobMapper.fromDocument(loop(time = null))!!.timestampMs)
        assertEquals(Instant.parse("2026-09-22T11:33:30.000Z").toEpochMilli(), IobMapper.fromDocument(loop(time = "garbage"))!!.timestampMs)
    }

    @Test
    fun integerValuesAreAccepted() {
        assertEquals(2.0, IobMapper.fromDocument(loop(iob = 2))!!.iob!!, 0.0)
    }

    @Test
    fun recordsWithoutLoopDataAreSkipped() {
        assertNull(IobMapper.fromDocument(Document("_id", oid).append("created_at", "2026-09-22T11:33:30.000Z").append("uploaderBattery", 80)))
        assertNull(IobMapper.fromDocument(Document("_id", oid).append("openaps", Document("enacted", Document()))))
        assertNull(IobMapper.fromDocument(loop().also { it.remove("_id") }))
    }

    @Test
    fun cobAloneIsStillUseful() {
        val d = Document("_id", "x").append("created_at", "2026-09-22T11:33:30.000Z").append("openaps", Document("suggested", Document("COB", 12)))
        val s = IobMapper.fromDocument(d)!!
        assertNull(s.iob); assertEquals(12.0, s.cob!!, 0.0)
    }
}
