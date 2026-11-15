package app.bganalyzer.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

class DataChecksTest {
    private val zone = ZoneId.of("Europe/London")
    private fun ms(d: LocalDate, h: Int = 12) = d.atTime(h, 0).atZone(zone).toInstant().toEpochMilli()
    private val today = LocalDate.of(2026, 11, 15)
    private val now = ms(today)
    private val period = Span(ms(today.minusDays(14), 0), now)
    private val all = listOf(Span(period.startMs - 1, now))

    private fun stamps(vararg days: Pair<LocalDate, Int>) = days.flatMap { (d, n) -> (0 until n).map { ms(d) + it * 60_000L } }

    @Test
    fun consecutiveEmptyDaysAreMergedIntoRanges() {
        val have = (0..13).map { today.minusDays(it.toLong()) }.filter { it !in listOf(today.minusDays(6), today.minusDays(7), today.minusDays(8), today.minusDays(3)) }
        val r = DataChecks.emptyRanges("treatments", stamps(*have.map { it to 20 }.toTypedArray()), all, period, zone, 5, now)
        assertEquals(listOf(EmptyRange("treatments", today.minusDays(8), today.minusDays(6)), EmptyRange("treatments", today.minusDays(3), today.minusDays(3))), r)
        assertEquals(3, r[0].days)
    }

    @Test
    fun aDayWithFewerThanTheMinimumCountsAsEmpty() {
        val have = (0..13).map { today.minusDays(it.toLong()) }.associateWith { 20 } + (today.minusDays(5) to 2)
        val r = DataChecks.emptyRanges("treatments", stamps(*have.toList().toTypedArray()), all, period, zone, 5, now)
        assertEquals(listOf(EmptyRange("treatments", today.minusDays(5), today.minusDays(5))), r)
    }

    @Test
    fun daysThatWereNeverRequestedAreNotReportedAsEmpty() {
        val half = listOf(Span(ms(today.minusDays(4), 0), now))   // only the last 4 days were ever asked for
        assertTrue(DataChecks.emptyRanges("iob", emptyList(), half, period, zone, 5, now).all { it.from >= today.minusDays(4) })
    }

    @Test
    fun todayYesterdayAndTheFirstPartialDayAreNeverReported() {
        val r = DataChecks.emptyRanges("glucose", emptyList(), all, period, zone, 5, now)
        assertEquals(today.minusDays(13), r.first().from)      // not today-14: that day is only partly in the period
        assertEquals(today.minusDays(2), r.last().to)           // not yesterday or today
    }
}
