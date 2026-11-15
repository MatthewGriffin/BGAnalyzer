package app.bganalyzer.autotune

import app.bganalyzer.domain.BasalSegment
import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneId

class AutotunePrepTest {
    private val zone = ZoneId.of("UTC")
    private val minute = 60_000L
    private val hour = 60 * minute
    private val tuned = AtProfile(List(24) { 1.0 }, 100.0, 10.0)
    private fun flatBasalDoses(hours: Int) = AutotuneDoses.build(emptyList(), listOf(BasalSegment(0, hours * hour, 1.0, true)), tuned, zone)
    private fun readings(hours: Int, f: (Int) -> Double) = (0 until hours * 12).map { AtReading(it * 5 * minute, f(it)) }

    @Test fun steadyGlucoseWithNormalBasalIsAllBasalData() {
        val p = AutotunePrep.categorize(PrepInput(readings(24) { 110.0 }, emptyList(), flatBasalDoses(24) + Dose(0, 0.0)), tuned, zone, 8.0)!!
        assertEquals(24 * 12 - 5, p.basalGlucose.size)
        assertTrue(p.csfGlucose.isEmpty() && p.isfGlucose.isEmpty() && p.crData.isEmpty())
        assertTrue(p.basalGlucose.all { it.deviation == 0.0 })
    }

    @Test fun noInsulinDataOrNoGlucoseGivesNull() {
        assertNull(AutotunePrep.categorize(PrepInput(readings(2) { 110.0 }, emptyList(), emptyList()), tuned, zone, 8.0))
        assertNull(AutotunePrep.categorize(PrepInput(emptyList(), emptyList(), flatBasalDoses(2)), tuned, zone, 8.0))
        assertNull(AutotunePrep.categorize(PrepInput(readings(2) { 30.0 }, emptyList(), flatBasalDoses(2)), tuned, zone, 8.0))
    }

    @Test fun aMealWithItsBolusGivesCarbAbsorptionAndACarbRatioDatum() {
        // 60 g and 6 U at 02:00 (plus 1.5 U later); glucose climbs 3 mg/dL per reading for two hours and then settles
        val t0 = 2 * hour
        val r = readings(12) { n ->
            val since = n - 24
            if (since < 0) 110.0 else 110.0 + 3 * minOf(since, 24) - maxOf(0, since - 48) * 1.0
        }
        // the meal bolus is in the starting IOB; only insulin given after the first carb reading counts as dosed
        val doses = flatBasalDoses(12) + Dose(t0 + minute, 6.0) + Dose(t0 + 30 * minute, 1.5)
        val p = AutotunePrep.categorize(PrepInput(r, listOf(AtMeal(t0, 60.0)), doses), tuned, zone, 8.0)!!
        assertTrue("carb absorption found", p.csfGlucose.isNotEmpty() || p.isfGlucose.isNotEmpty())
        val first = p.csfGlucose.firstOrNull()
        if (first != null) assertEquals("start", first.mealAbsorption)
        assertEquals(1, p.crData.size)
        p.crData.forEach { assertEquals(60.0, it.carbs, 0.0); assertEquals(1.5, it.insulin, 0.0); assertTrue(it.initialIob > 4.0) }
    }

    @Test fun tuningTheInsulinCurveGivesFiveDeviationsEach() {
        val p = AutotunePrep.categorize(
            PrepInput(readings(24) { 110.0 }, emptyList(), flatBasalDoses(24)), tuned, zone, 8.0, PrepOptions(tuneInsulinCurve = true),
        )!!
        assertEquals(listOf(4.0, 5.0, 6.0, 7.0, 8.0), p.diaDeviations.map { it.dia })
        assertEquals(listOf(65, 70, 75, 80, 85), p.peakDeviations.map { it.peak })
    }

    @Test fun prepOutputFeedsTheCore() {
        val p = AutotunePrep.categorize(PrepInput(readings(24) { 110.0 }, emptyList(), flatBasalDoses(24)), tuned, zone, 8.0)!!
        val out = AutotuneCore.tune(p, tuned, tuned, AutotuneLimits(), zone)
        assertEquals(tuned.isf, out.isf, 1e-9)
        out.basal.forEach { assertEquals(1.0, it, 1e-9) }
    }
}
