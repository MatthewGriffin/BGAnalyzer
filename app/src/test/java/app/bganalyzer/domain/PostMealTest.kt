package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.TreatmentEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

class PostMealTest {
    private val zone = ZoneId.of("Europe/London")
    private val day = LocalDate.of(2026, 9, 1)
    private fun at(h: Int, m: Int = 0) = day.atTime(h, m).atZone(zone).toInstant().toEpochMilli()

    private fun treatment(t: Long, carbs: Double?, valid: Boolean = true, id: String = "t$t") =
        TreatmentEntity(id, t, "Meal Bolus", 2.0, carbs, false, null, null, null, valid, null, "{}")

    /** Glucose every 5 minutes from 06:00 to 14:00, built from minutes after 08:00. */
    private fun curve(f: (Int) -> Double): List<GlucoseReadingEntity> =
        (at(6)..at(14) step 300_000).map { GlucoseReadingEntity(it, f(((it - at(8)) / 60_000).toInt())) }

    @Test
    fun carbsOnBolusRecordsBecomeMealsAndNearbyEntriesAreMerged() {
        val meals = PostMeal.meals(
            listOf(
                treatment(at(8), 30.0), treatment(at(8, 20), 10.0), treatment(at(12), 40.0),
                treatment(at(13), null), treatment(at(13, 30), 20.0, valid = false), treatment(at(9, 30), 3.0),
            ),
        )
        assertEquals(listOf(Meal(at(8), 40.0), Meal(at(12), 40.0)), meals)
    }

    @Test
    fun riseAndTwoHourValueAreMeasuredFromTheMeal() {
        // Flat 100 until 08:00, climbing 1 mg/dL per minute to a 160 peak at 09:00, then 130 from 10:00 on.
        val r = curve { m -> when { m <= 0 -> 100.0; m <= 60 -> 100.0 + m; m < 120 -> 160.0 - (m - 60) * 0.5; else -> 130.0 } }
        val stats = PostMeal.analyze(r, listOf(Meal(at(8), 40.0)), zone, 6)
        val s = stats[1] // 06:00-12:00
        assertEquals(1, s.meals); assertEquals(60.0, s.medianRiseMgdl, 1e-9); assertEquals(130.0, s.medianAt2hMgdl!!, 1e-9)
        assertEquals(0, s.highAt2h); assertEquals(1, s.withReading2h); assertEquals(0, s.lowWithin4h)
    }

    @Test
    fun mealsFollowedByALowAreCounted() {
        val r = curve { m -> if (m in 150..200) 60.0 else 110.0 }
        assertEquals(1, PostMeal.analyze(r, listOf(Meal(at(8), 30.0)), zone, 6)[1].lowWithin4h)
    }

    @Test
    fun mealsEatenWhileAlreadyLowAreSkippedAsHypoTreatments() {
        val r = curve { 55.0 }
        assertEquals(0, PostMeal.analyze(r, listOf(Meal(at(8), 15.0)), zone, 6)[1].meals)
    }

    @Test
    fun mealsWithoutEnoughReadingsAroundThemAreSkipped() {
        val gappy = curve { 100.0 }.filter { it.timestampMs < at(8, 30) }
        assertEquals(0, PostMeal.analyze(gappy, listOf(Meal(at(8), 30.0)), zone, 6).sumOf { it.meals })
    }

    @Test
    fun noBaselineMeansNoMeasurement() {
        val r = curve { 100.0 }.filter { it.timestampMs > at(8) }
        assertNull(PostMeal.analyze(r, listOf(Meal(at(8), 30.0)), zone, 6).firstOrNull { it.meals > 0 })
        assertNotNull(PostMeal.analyze(curve { 100.0 }, listOf(Meal(at(8), 30.0)), zone, 6).firstOrNull { it.meals > 0 })
    }
}
