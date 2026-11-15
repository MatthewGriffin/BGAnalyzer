package app.bganalyzer.domain

import org.junit.Assert.*
import org.junit.Test

class SuggestionsTest {
    private fun tir(high: Int, total: Int = 100) = TimeInRange(total, 0, 0, total - high, high, 0, 150.0)
    private fun block(start: Int, high: Int = 40, lowDays: Int = 0, days: Int = 20) =
        BlockStats(start, start + 6, days, days * 72, tir(high), lowDays, 0)
    private fun basal(start: Int, above: Double, below: Double, actual: Double, sched: Double, days: Int = 20) =
        BasalBlockStats(start, start + 6, days, above, below, 100 - above - below, 0.0, actual, sched)
    private fun result(vararg b: BasalBlockStats) =
        BasalComparisonResult(b[0], b.toList(), 90.0, 10, 5, 5, 0, 30.0)

    @Test fun basalIncreaseIsCappedAtTwentyPercent() {
        val r = Suggestions.generate(listOf(block(0)), emptyList(), result(basal(0, 80.0, 10.0, 1.5, 1.0)))
        val s = r.suggestions.single()
        assertTrue(s.moreInsulin); assertEquals(20, s.changePct); assertEquals(1.2, s.toUph!!, 1e-9)
    }

    @Test fun basalIncreaseIsCappedAtHalfUnitPerHour() {
        val r = Suggestions.generate(listOf(block(0)), emptyList(), result(basal(0, 90.0, 0.0, 4.0, 3.0)))
        assertEquals(3.5, r.suggestions.single().toUph!!, 1e-9)
    }

    @Test fun lowsStopAnIncreaseOnlyInThatBlock() {
        val r = Suggestions.generate(
            listOf(block(0, lowDays = 4), block(6)), emptyList(),
            result(basal(0, 80.0, 10.0, 1.5, 1.0), basal(6, 80.0, 10.0, 1.5, 1.0)),
        )
        assertEquals(listOf(6), r.suggestions.map { it.startHour })
        assertEquals(listOf(0), r.held.map { it.startHour })
    }

    @Test fun basalDecreaseFollowsLoopRunningBelow() {
        val r = Suggestions.generate(listOf(block(0, high = 5)), emptyList(), result(basal(0, 5.0, 85.0, 0.7, 1.0)))
        assertFalse(r.suggestions.single().moreInsulin)
    }

    @Test fun tooFewDaysGivesNothing() {
        val r = Suggestions.generate(listOf(block(0)), emptyList(), result(basal(0, 90.0, 0.0, 1.5, 1.0, days = 3)))
        assertTrue(r.suggestions.isEmpty())
    }

    @Test fun carbRatioHighAfterMealsAndLowsAfterMeals() {
        val high = MealBlockStats(0, 6, 10, 80.0, 200.0, 8, 10, 0)
        val low = MealBlockStats(6, 12, 10, 40.0, 100.0, 0, 10, 4)
        val r = Suggestions.generate(listOf(block(0), block(6)), listOf(high, low), null)
        assertTrue(r.suggestions.first { it.startHour == 0 }.moreInsulin)
        assertFalse(r.suggestions.first { it.startHour == 6 }.moreInsulin)
    }
}

class FastingDriftSuggestionTest {
    private fun block(start: Int, lowDays: Int = 0) = BlockStats(start, start + 6, 20, 1440, TimeInRange(100, 0, 0, 80, 20, 0, 150.0), lowDays, 0)
    private fun drift(slope: Double, up: Int, down: Int, days: Int = 10) = listOf(DriftBlockStats(0, 6, days, slope, up, down))

    @Test fun risingWithoutFoodSuggestsMoreBasalWithoutLoopData() {
        val s = Suggestions.generate(listOf(block(0)), emptyList(), null, drift(12.0, 8, 0), mapOf(0 to 1.0)).suggestions.single()
        assertTrue(s.moreInsulin); assertEquals(1.1, s.toUph!!, 1e-9)
    }

    @Test fun fallingWithoutFoodSuggestsLessBasalEvenWithLows() {
        val s = Suggestions.generate(listOf(block(0, lowDays = 5)), emptyList(), null, drift(-20.0, 0, 9), mapOf(0 to 1.0)).suggestions.single()
        assertFalse(s.moreInsulin); assertEquals(20, s.changePct)
    }

    @Test fun risingWithLowsIsHeld() {
        val r = Suggestions.generate(listOf(block(0, lowDays = 5)), emptyList(), null, drift(12.0, 8, 0), mapOf(0 to 1.0))
        assertTrue(r.suggestions.isEmpty()); assertEquals(1, r.held.size)
    }

    @Test fun mixedDaysGiveNothing() {
        assertTrue(Suggestions.generate(listOf(block(0)), emptyList(), null, drift(9.0, 5, 4), mapOf(0 to 1.0)).suggestions.isEmpty())
    }
}
