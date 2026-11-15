package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.TreatmentEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MomentTest {
    private val min = 60_000L
    private val t0 = 1_790_000_000_000L
    private fun r(offsetMin: Int, v: Double) = GlucoseReadingEntity(t0 + offsetMin * min, v)
    private fun tr(offsetMin: Int, carbs: Double?, insulin: Double?, smb: Boolean = false, valid: Boolean = true) =
        TreatmentEntity("t$offsetMin", t0 + offsetMin * min, "Meal Bolus", insulin, carbs, smb, null, null, null, valid, null, "{}")

    @Test
    fun picksTheNearestReadingWithinTenMinutes() {
        val m = Moment.at(t0 + 7 * min, listOf(r(0, 100.0), r(5, 110.0), r(10, 120.0)), emptyList(), emptyList())
        assertEquals(110.0, m.mgdl!!, 0.0)       // the 5-minute reading is 2 min away, the 10-minute one 3 min away
        assertEquals(-2 * min, m.readingOffsetMs)
    }

    @Test
    fun noReadingNearMeansNoValue() {
        assertNull(Moment.at(t0 + 60 * min, listOf(r(0, 100.0)), emptyList(), emptyList()).mgdl)
        assertNull(Moment.at(t0, emptyList(), emptyList(), emptyList()).mgdl)
    }

    @Test
    fun sumsAndLatestEventsLookBackOnly() {
        val m = Moment.at(
            t0 + 120 * min, emptyList(),
            listOf(tr(0, 30.0, 3.0), tr(60, null, 0.3, smb = true), tr(100, 10.0, null), tr(110, 99.0, 9.0, valid = false), tr(130, 50.0, 5.0)),
            emptyList(),
        )
        assertEquals(40.0, m.carbsLast3h, 0.0); assertEquals(3.3, m.bolusLast3h, 1e-9)
        assertEquals(10.0 to 20 * min, m.lastCarbs)
        assertEquals(Triple(0.3, true, 60 * min), m.lastBolus)
    }

    @Test
    fun eventsOlderThanThreeHoursAreNotSummedButStillReportedAsLast() {
        val m = Moment.at(t0 + 400 * min, emptyList(), listOf(tr(0, 30.0, 3.0)), emptyList())
        assertEquals(0.0, m.carbsLast3h, 0.0); assertEquals(30.0 to 400 * min, m.lastCarbs)
    }

    @Test
    fun basalIsTheSegmentContainingTheMoment() {
        val segs = listOf(BasalSegment(t0, t0 + 30 * min, 1.0, false), BasalSegment(t0 + 30 * min, t0 + 60 * min, 0.5, true))
        assertEquals(0.5, Moment.at(t0 + 30 * min, emptyList(), emptyList(), segs).basal!!.rateUph, 0.0)
        assertNull(Moment.at(t0 + 61 * min, emptyList(), emptyList(), segs).basal)
    }
}
