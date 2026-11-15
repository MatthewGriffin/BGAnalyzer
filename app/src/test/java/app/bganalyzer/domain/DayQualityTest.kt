package app.bganalyzer.domain

import app.bganalyzer.data.TreatmentEntity
import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneId

class DayQualityTest {
    private val zone = ZoneId.of("UTC")
    private val day = 86_400_000L
    private val origin = 1_793_491_200_000L // 2026-11-01 00:00 UTC
    private fun bolus(t: Long) = TreatmentEntity("b$t", t, "Meal Bolus", 2.0, null, false, null, null, null, true, null, "{}")
    private fun temp(t: Long, minutes: Long = 5) = TreatmentEntity("t$t", t, "Temp Basal", null, null, false, 1.0, minutes * 60_000L, null, true, null, "{}")

    @Test fun aBolusOrManyTempBasalsCountAsInsulin() {
        val t = listOf(bolus(origin + 1000)) + (0 until 25).map { temp(origin + day + it * 300_000L) } + (0 until 5).map { temp(origin + 2 * day + it * 300_000L) }
        assertEquals(setOf("2026-11-01", "2026-11-02"), DayQuality.daysWithInsulin(t, zone))
    }

    @Test fun aTempBasalRecordedAsEightyHoursIsNotEvidence() {
        val t = (0 until 30).map { temp(origin + it * 60_000L, minutes = 4800) }
        assertTrue(DayQuality.daysWithInsulin(t, zone).isEmpty())
    }

    @Test fun daysWithGlucoseButNoInsulinAreListedExceptRecentOnes() {
        val readings = (0 until 6 * 288).map { origin + it * 300_000L }
        val t = listOf(bolus(origin + 1000)) // 2026-11-01 only
        val now = origin + 5 * day + 3_600_000L // 2026-11-06 01:00
        val missing = DayQuality.daysWithoutInsulin(t, readings, zone, origin, origin + 6 * day, now)
        assertEquals(listOf("2026-11-02", "2026-11-03", "2026-11-04"), missing) // 11-05 and 11-06 are recent, 11-01 has a bolus
    }
}
