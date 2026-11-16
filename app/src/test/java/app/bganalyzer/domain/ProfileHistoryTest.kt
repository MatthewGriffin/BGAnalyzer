package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneOffset

class ProfileHistoryTest {
    private val day = 86_400_000L
    private fun p(startDays: Long, rate: Double) = EffectiveProfile(startDays * day, "main", 100, 0, 0, listOf(BasalStep(0, rate)), EffectiveProfile.Source.EFFECTIVE_RECORD)
    private fun readings(fromDay: Int, toDay: Int, mgdl: Double) = (fromDay * 288 until toDay * 288).map { GlucoseReadingEntity(it * 300_000L, mgdl) }

    @Test fun listsEveryConfigurationNewestFirstWithItsOwnGlucose() {
        val r = readings(0, 10, 120.0) + readings(10, 20, 250.0)
        val h = ProfileHistory.build(r, listOf(p(0, 1.0), p(10, 1.2), p(12, 1.2)), ZoneOffset.UTC, 20 * day)
        assertEquals(listOf(10 * day, 0L), h.map { it.profile.startMs }) // the same settings again on day 12 is not a new configuration
        assertNull(h[0].endMs); assertEquals(10 * day, h[1].endMs)
        assertEquals(100.0, h[1].summary.timeInRange.inRangePct, 0.1)
        assertEquals(0.0, h[0].summary.timeInRange.inRangePct, 0.1)
    }

    @Test fun aConfigurationWithoutGlucoseStillAppears() {
        val h = ProfileHistory.build(emptyList(), listOf(p(0, 1.0), p(3, 1.5)), ZoneOffset.UTC, 5 * day)
        assertEquals(2, h.size)
        assertEquals(0, h[0].summary.readings)
    }
}
