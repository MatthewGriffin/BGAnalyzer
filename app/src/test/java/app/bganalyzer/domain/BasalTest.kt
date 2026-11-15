package app.bganalyzer.domain

import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

class BasalTest {
    private val zone = ZoneId.of("Europe/London")
    private val d = LocalDate.of(2026, 9, 1)
    private fun at(h: Int, m: Int = 0) = d.atTime(h, m).atZone(zone).toInstant().toEpochMilli()
    private val minute = 60_000L

    private fun temp(startMs: Long, rate: Double, durMin: Int, valid: Boolean = true) =
        TreatmentEntity("t$startMs", startMs, "Temp Basal", null, null, false, rate, durMin * minute, null, valid, null, "{}")

    private fun profile(startMs: Long, vararg steps: Pair<Int, Double>) = ProfileEntity(
        "p$startMs", startMs, "main", "mmol", "Europe/London",
        """{"defaultProfile":"main","store":{"main":{"basal":[${steps.joinToString(",") { """{"time":"x","timeAsSeconds":${it.first},"value":${it.second}}""" }}]}}}""",
    )

    private val flat = profile(0, 0 to 0.8)

    @Test
    fun scheduleIsReadFromTheDefaultProfile() {
        assertEquals(listOf(BasalStep(0, 0.7), BasalStep(21600, 0.9)), BasalTimeline.schedule(profile(0, 21600 to 0.9, 0 to 0.7)))
    }

    @Test
    fun tempBasalsRunForTheirDurationAndGapsUseTheSchedule() {
        val seg = BasalTimeline.build(listOf(temp(at(8), 1.5, 30)), listOf(flat), at(7), at(9), zone)
        assertEquals(
            listOf(
                BasalSegment(at(7), at(8), 0.8, true),
                BasalSegment(at(8), at(8, 30), 1.5, false),
                BasalSegment(at(8, 30), at(9), 0.8, true),
            ),
            seg,
        )
    }

    @Test
    fun aNewTempBasalCutsOffTheEarlierOne() {
        val seg = BasalTimeline.build(listOf(temp(at(8), 1.5, 30), temp(at(8, 10), 0.0, 30)), listOf(flat), at(8), at(8, 40), zone)
        assertEquals(listOf(BasalSegment(at(8), at(8, 10), 1.5, false), BasalSegment(at(8, 10), at(8, 40), 0.0, false)), seg)
    }

    @Test
    fun aZeroLengthRecordJustEndsThePreviousTempBasal() {
        val seg = BasalTimeline.build(listOf(temp(at(8), 1.5, 30), temp(at(8, 10), 0.0, 0)), listOf(flat), at(8), at(8, 20), zone)
        assertEquals(listOf(BasalSegment(at(8), at(8, 10), 1.5, false), BasalSegment(at(8, 10), at(8, 20), 0.8, true)), seg)
    }

    @Test
    fun aTempBasalStartedBeforeTheWindowStillCoversItsStart() {
        val seg = BasalTimeline.build(listOf(temp(at(7, 30), 1.2, 60)), listOf(flat), at(8), at(9), zone)
        assertEquals(listOf(BasalSegment(at(8), at(8, 30), 1.2, false), BasalSegment(at(8, 30), at(9), 0.8, true)), seg)
    }

    @Test
    fun scheduleStepsSplitAGapAndInvalidTempsAreIgnored() {
        val p = profile(0, 0 to 0.6, 21600 to 1.0, 43200 to 0.5)
        val seg = BasalTimeline.build(listOf(temp(at(5), 9.0, 30, valid = false)), listOf(p), at(5), at(7), zone)
        assertEquals(listOf(BasalSegment(at(5), at(6), 0.6, true), BasalSegment(at(6), at(7), 1.0, true)), seg)
    }

    @Test
    fun withoutAProfileGapsStayEmpty() {
        assertTrue(BasalTimeline.build(emptyList(), emptyList(), at(5), at(7), zone).isEmpty())
    }
}
