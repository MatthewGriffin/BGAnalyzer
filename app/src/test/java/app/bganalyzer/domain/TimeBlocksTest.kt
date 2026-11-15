package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

class TimeBlocksTest {
    private val london = ZoneId.of("Europe/London")

    /** One reading every 5 minutes over [days] local days from [first], with glucose from [value] by local hour. */
    private fun readings(first: LocalDate, days: Int, value: (Int) -> Double): List<GlucoseReadingEntity> {
        val start = first.atStartOfDay(london).toInstant().toEpochMilli()
        val end = first.plusDays(days.toLong()).atStartOfDay(london).toInstant().toEpochMilli()
        return generateSequence(start) { it + 300_000 }.takeWhile { it < end }
            .map { GlucoseReadingEntity(it, value(TimeBlocks.localHour(it, london))) }.toList()
    }

    @Test
    fun hoursAreGroupedByLocalTimeNotUtc() {
        // In BST (UTC+1) local 00:30 is 23:30 UTC the day before.
        val localMidnightHalf = LocalDate.of(2026, 7, 1).atTime(0, 30).atZone(london).toInstant().toEpochMilli()
        assertEquals(0, TimeBlocks.localHour(localMidnightHalf, london))
        assertEquals(23, TimeBlocks.localHour(localMidnightHalf, ZoneId.of("UTC")))
    }

    @Test
    fun overnightLowsAreFoundOnlyInTheOvernightBlock() {
        val r = readings(LocalDate.of(2026, 9, 1), 7) { h -> if (h < 6) 60.0 else 120.0 }
        val blocks = TimeBlocks.analyze(r, london, 6)
        assertEquals(4, blocks.size)
        assertEquals(7, blocks[0].days); assertEquals(7, blocks[0].lowDays)
        assertEquals(100.0, blocks[0].timeInRange.lowPct, 1e-9)
        assertEquals(0, blocks[1].lowDays); assertEquals(100.0, blocks[1].timeInRange.inRangePct, 1e-9)
        assertTrue(blocks[0].enoughDays)
    }

    @Test
    fun fewDaysAreFlaggedAsNotEnough() {
        val b = TimeBlocks.analyze(readings(LocalDate.of(2026, 9, 1), 3) { 100.0 }, london, 6)
        assertEquals(3, b[0].days); assertFalse(b[0].enoughDays)
    }

    @Test
    fun sparseDaysAreLeftOut() {
        // Day 1 has only 10 of 72 expected readings in the overnight block.
        val dense = readings(LocalDate.of(2026, 9, 2), 6) { 100.0 }
        val sparse = readings(LocalDate.of(2026, 9, 1), 1) { 100.0 }.take(10)
        val b = TimeBlocks.analyze(sparse + dense, london, 6)
        assertEquals(6, b[0].days)
    }

    @Test
    fun theLongDayWhenClocksGoBackKeepsEveryHourInItsOwnBlock() {
        // 2026-10-25 has 25 hours in London. Local hour 1 happens twice, so block 0 holds 7 hours of readings.
        val day = readings(LocalDate.of(2026, 10, 25), 1) { 100.0 }
        assertEquals(25 * 12, day.size)
        val b = TimeBlocks.analyze(day, london, 6)
        assertEquals(7 * 12, b[0].readings)
        assertEquals(6 * 12, b[1].readings); assertEquals(6 * 12, b[2].readings); assertEquals(6 * 12, b[3].readings)
        assertEquals(1, b[0].days); assertEquals(1, b[3].days)
    }

    @Test
    fun theShortDayWhenClocksGoForwardStillCountsAsADay() {
        // 2026-03-29 has 23 hours: local 01:00-02:00 does not exist.
        val day = readings(LocalDate.of(2026, 3, 29), 1) { 100.0 }
        assertEquals(23 * 12, day.size)
        val b = TimeBlocks.analyze(day, london, 6)
        assertEquals(5 * 12, b[0].readings); assertEquals(1, b[0].days)
    }
}
