package app.bganalyzer.autotune

import app.bganalyzer.domain.BasalSegment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

class AutotuneIobTest {
    private val minute = 60_000L

    @Test fun insulinCurveMatchesTheAapsFormulaValues() {
        // Expected values come from the Python port on desktop-final, which matches AAPS LocalInsulin.
        val li = LocalInsulin(75, 6.0)
        fun check(m: Int, iob: Double, act: Double) = li.contribution(2.5, 0, m * minute).let {
            assertEquals(iob, it.first, 1e-12); assertEquals(act, it.second, 1e-12)
        }
        check(0, 2.5, 0.0)
        check(30, 2.3238021574326897, 0.010293815706987836)
        check(75, 1.7356583592954264, 0.0142837894969308)
        check(180, 0.520426835784449, 0.007717440389127225)
        check(360, 0.0, 0.0)
        val y = LocalInsulin(45, 7.0).contribution(1.0, 0, 10 * minute)
        assertEquals(0.9781463193491593, y.first, 1e-12); assertEquals(0.0040564632827573876, y.second, 1e-12)
    }

    @Test fun diaBelowFiveHoursIsRaisedToFive() = assertEquals(5.0, LocalInsulin(75, 3.0).diaHours, 0.0)

    @Test fun basalEqualToTheTunedProfileAddsNoInsulin() {
        val tuned = AtProfile(List(24) { 1.0 }, 100.0, 10.0)
        val doses = AutotuneDoses.build(emptyList(), listOf(BasalSegment(0, 3 * 60 * minute, 1.0, true)), tuned, ZoneId.of("UTC"))
        assertTrue(doses.all { it.units == 0.0 })
        assertEquals(0.0, IobCurve(doses, LocalInsulin()).at(3 * 60 * minute).iob, 0.0)
    }

    @Test fun extraBasalAddsUpToTheRateTimesTheTime() {
        val tuned = AtProfile(List(24) { 1.0 }, 100.0, 10.0)
        // 2 U/h for 90 minutes against a tuned 1 U/h: 1.5 U more than normal
        val doses = AutotuneDoses.build(emptyList(), listOf(BasalSegment(0, 90 * minute, 2.0, false)), tuned, ZoneId.of("UTC"))
        assertEquals(1.5, doses.sumOf { it.units }, 1e-9)
        assertTrue(doses.all { it.timeMs in 0..90 * minute })
    }

    @Test fun suspendedBasalRemovesInsulin() {
        val tuned = AtProfile(List(24) { 1.0 }, 100.0, 10.0)
        val doses = AutotuneDoses.build(emptyList(), listOf(BasalSegment(0, 60 * minute, 0.0, false)), tuned, ZoneId.of("UTC"))
        assertEquals(-1.0, doses.sumOf { it.units }, 1e-9)
    }

    @Test fun iobCurveSumsBolusesInsideTheInsulinWindowOnly() {
        val curve = IobCurve(listOf(Dose(0, 2.5), Dose(10 * 60 * minute, 1.0)), LocalInsulin(75, 6.0))
        assertEquals(1.736, curve.at(75 * minute).iob, 1e-3)
        assertEquals(0.0, curve.at(7 * 60 * minute).iob, 0.0)
    }
}
