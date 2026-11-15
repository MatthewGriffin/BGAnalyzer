package app.bganalyzer.autotune

import app.bganalyzer.domain.BasalSegment
import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneId

/**
 * End-to-end check on a simulated person with a known true insulin need. Glucose is generated with the same insulin
 * curve autotune assumes, from the true needs, while the pump delivers the (wrong) profile. Autotune should move the
 * profile toward the truth and leave correct parts alone.
 */
class AutotuneSimulationTest {
    private val zone = ZoneId.of("UTC")
    private val hour = 3_600_000L
    private val day = 24 * hour
    private val origin = 1_793_491_200_000L // 2026-11-01 00:00 UTC
    private val end = origin + 9 * day + 4 * hour
    private val isf = 50.0
    private val ic = 10.0
    private val profile = AtProfile(List(24) { 1.0 }, isf, ic)
    private val insulin = LocalInsulin(profile.peak, profile.dia)

    /** True basal need: 1.15 U/h from 01:00 to 06:00 (the profile gives 1.0), otherwise right. */
    private fun trueBasal(h: Int) = if (h in 1..5) 1.15 else 1.0

    private fun simulate(mealsPerDay: Boolean, carbRatioTruth: Double = ic): AutotuneData {
        val meals = if (mealsPerDay) (0..9).flatMap { d -> listOf(8, 13, 19).map { AtMeal(origin + d * day + it * hour, 50.0) } } else emptyList()
        // the person doses by the profile ratio, the body follows carbRatioTruth
        // a tiny daily bolus marks "the pump was running" (days with no insulin records are skipped)
        val boluses = meals.map { Dose(it.timeMs - 5 * 60_000L, it.carbs / ic) } + (0..9).map { Dose(origin + it * day + 23 * hour, 0.01) }
        val readings = ArrayList<AtReading>()
        var bg = 110.0
        val steps = 10 * 288
        val curve = IobCurve(boluses, insulin)
        for (i in 0 until steps) {
            val t = origin + i * 300_000L
            readings += AtReading(t, bg)
            val h = ((t - origin) / hour % 24).toInt()
            // basal shortfall raises glucose: (need - delivered) U/h * ISF / 12 per 5 minutes
            val basalGap = (trueBasal(h) - 1.0) * isf / 12
            val bolusFall = curve.at(t).activity * isf * 5
            // carbs: 50 g spread over 2 hours, worth 50 / carbRatioTruth units * ISF
            val carbRise = meals.sumOf { m ->
                val mins = (t - m.timeMs) / 60_000.0
                if (mins in 0.0..120.0) m.carbs / carbRatioTruth * isf / 24 else 0.0
            }
            bg += basalGap - bolusFall + carbRise
        }
        return AutotuneData(readings, boluses, meals) { f, t -> listOf(BasalSegment(f, t, 1.0, true)) }
    }

    @Test fun fastingBasalGapRaisesTheHoursItsRiseIsCreditedTo() {
        val r = AutotuneRun.run(simulate(false), profile, AutotuneLimits(), zone, end, 7)
        assertTrue("days tuned ${r.daysTuned}, skipped ${r.skipped}", r.daysTuned >= 6)
        val b = r.tuned.basal
        // Glucose rises in the true 01:00-06:00 shortfall. As in oref0 a rise is credited to the three hours before it
        // (22:00 to 04:00 here), so those hours go up, none beyond the autosens limit.
        val credited = listOf(22, 23, 0, 1, 2, 3, 4).map { b[it] }
        assertTrue("credited hours $credited", credited.average() > 1.07)
        assertTrue("capped at autosens max", b.all { it <= 1.2 + 1e-9 })
        // The rest stays near the profile (the ends relax slowly toward the changed neighbours, as in AAPS)
        val rest = (5..20).map { b[it] }
        assertTrue("other hours $rest", rest.all { it in 0.93..1.03 })
    }

    @Test fun mealsDosedByTheTrueRatioLeaveTheCarbRatioAndIsfNear() {
        val r = AutotuneRun.run(simulate(true), profile, AutotuneLimits(), zone, end, 7)
        assertTrue(r.daysTuned >= 6)
        assertTrue("ISF ${r.tuned.isf}", r.tuned.isf in isf * 0.8..isf * 1.2)
        assertTrue("carb ratio ${r.tuned.ic}", r.tuned.ic in ic * 0.8..ic * 1.2)
    }

    @Test fun rerunningTheSameDaysFromTheAppliedResultMovesTheValuesFurther() {
        // This is why days run on the old profile must not be replayed again: each run starts from its input profile.
        val data = simulate(false)
        val first = AutotuneRun.run(data, profile, AutotuneLimits(), zone, end, 7)
        val second = AutotuneRun.run(data, first.tuned, AutotuneLimits(), zone, end, 7)
        val night = listOf(23, 0, 1, 2)
        assertTrue(night.sumOf { second.tuned.basal[it] } > night.sumOf { first.tuned.basal[it] } + 0.01)
    }

    @Test fun afterAProfileChangeOnlyLaterDaysAreUsedSoNothingDriftsFurther() {
        val data = simulate(false)
        val first = AutotuneRun.run(data, profile, AutotuneLimits(), zone, end, 7)
        // the tuned values were applied at the end of the data: no day starts after that
        val again = AutotuneRun.run(data, first.tuned, AutotuneLimits(), zone, end, 7, notBeforeMs = end, notBeforeReason = "before your profile change")
        assertEquals(0, again.daysTuned)
        assertEquals(first.tuned, again.tuned)
        assertTrue(again.skipped.all { it.reason == "before your profile change" })
        // a change midway keeps only the days that started after it
        val midway = AutotuneRun.run(data, profile, AutotuneLimits(), zone, end, 7, notBeforeMs = origin + 5 * day + 4 * hour)
        assertEquals(4, midway.daysTuned) // the seven windows start 3 to 9 Nov at 04:00; those from 6 Nov 04:00 on are kept
    }
}
