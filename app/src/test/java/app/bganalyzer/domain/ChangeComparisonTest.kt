package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import org.junit.Assert.*
import org.junit.Test

class ChangeComparisonTest {
    private val day = 86_400_000L
    private fun profile(startDays: Int, rate: Double) = EffectiveProfile(startDays * day, "main", 100, 0, 0, listOf(BasalStep(0, rate)), EffectiveProfile.Source.EFFECTIVE_RECORD)
    private fun readings(fromDay: Int, toDay: Int, mgdl: Double) =
        (fromDay * 288 until toDay * 288).map { GlucoseReadingEntity(it * 300_000L, mgdl) }

    @Test fun comparesTheWeekBeforeAndAfterAChange() {
        val changes = listOf(profile(0, 1.0), profile(10, 1.2))
        val r = readings(3, 10, 200.0) + readings(10, 17, 120.0)
        val res = ChangeComparison.compare(r, changes, 5 * day, 30 * day).single()
        assertEquals(0.0, res.before.timeInRange.inRangePct, 0.1)
        assertEquals(100.0, res.after.timeInRange.inRangePct, 0.1)
        assertEquals(24.0, res.basalPerDayBefore!!, 1e-9); assertEquals(28.8, res.basalPerDayAfter, 1e-9)
        assertTrue(res.before.enough && res.after.enough)
    }

    @Test fun windowsStopAtTheNextChange() {
        val changes = listOf(profile(10, 1.0), profile(12, 1.1))
        val res = ChangeComparison.compare(readings(0, 20, 120.0), changes, 0, 30 * day)
        assertEquals(2.0, res[0].after.days, 1e-9)
    }

    @Test fun tooLittleDataIsNotEnough() {
        val res = ChangeComparison.compare(readings(9, 11, 120.0), listOf(profile(10, 1.0)), 0, 11 * day).single()
        assertFalse(res.after.enough)
    }

    @Test fun totalBasalAddsUpASchedule() = assertEquals(25.0, ChangeComparison.totalBasal(listOf(BasalStep(0, 1.0), BasalStep(12 * 3600, 1.0833333333333333))), 0.01)
}
