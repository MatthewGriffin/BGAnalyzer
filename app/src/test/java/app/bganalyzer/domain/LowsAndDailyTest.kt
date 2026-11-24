package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

class LowsAndDailyTest {
    private val zone = ZoneId.of("UTC")
    private val t0 = java.time.Instant.parse("2026-11-10T00:00:00Z").toEpochMilli()
    private val min = 60_000L
    private fun r(atMin: Long, mgdl: Double) = GlucoseReadingEntity(t0 + atMin * min, mgdl)

    @Test fun oneEpisodeWithItsLowestAndLength() {
        val s = Lows.summarize(listOf(r(0, 100.0), r(5, 65.0), r(10, 52.0), r(15, 60.0), r(20, 90.0)), zone)
        assertEquals(1, s.count); assertEquals(52.0, s.lowestMgdl!!, 0.0); assertEquals(10, s.averageMinutes); assertEquals(1, s.veryLowEpisodes)
    }

    @Test fun aGapOverTwentyMinutesSplitsEpisodes() {
        val s = Lows.summarize(listOf(r(0, 60.0), r(5, 60.0), r(60, 60.0), r(65, 90.0)), zone)
        assertEquals(2, s.count)
    }

    @Test fun worstHourIsTheBusiestOne() {
        val s = Lows.summarize(listOf(r(180, 60.0), r(185, 90.0), r(780, 60.0), r(785, 90.0), r(1620, 60.0), r(1625, 90.0)), zone)
        assertEquals(3, s.worstHour)
    }

    @Test fun noLowsMeansNoWorstHour() = assertTrue(Lows.summarize(listOf(r(0, 100.0)), zone).worstHour == null)

    @Test fun dailyListCoversEmptyDays() {
        val days = DailyRange.of(listOf(r(0, 100.0), r(5, 200.0)), zone, t0, t0 + 3 * 24 * 60 * min)
        assertEquals(3, days.size); assertEquals(2, days[0].readings); assertEquals(0, days[1].readings)
        assertEquals(50.0, days[0].timeInRange.inRangePct, 0.0); assertTrue(!days[0].complete)
    }
}
