package app.bganalyzer.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SyncPlannerTest {
    private val min = 60_000L
    private val hour = 60 * min
    private val day = SyncPlanner.DAY_MS
    private val now = 1_790_000_000_000L

    @Test
    fun mergeJoinsOverlappingTouchingAndNearSpans() {
        assertEquals(
            listOf(Span(0, 30), Span(50, 60)),
            Intervals.merge(listOf(Span(10, 20), Span(0, 10), Span(15, 30), Span(50, 60), Span(55, 55))),
        )
        assertEquals(listOf(Span(0, 60)), Intervals.merge(listOf(Span(0, 10), Span(50, 60)), joinWithinMs = 40))
    }

    @Test
    fun subtractLeavesOnlyTheUncoveredParts() {
        val whole = Span(0, 100)
        assertEquals(listOf(Span(0, 100)), Intervals.subtract(whole, emptyList()))
        assertEquals(emptyList<Span>(), Intervals.subtract(whole, listOf(Span(-10, 120))))
        assertEquals(listOf(Span(0, 20), Span(40, 70), Span(90, 100)), Intervals.subtract(whole, listOf(Span(20, 40), Span(70, 90))))
        assertEquals(listOf(Span(50, 100)), Intervals.subtract(whole, listOf(Span(-5, 50))))
    }

    @Test
    fun aNeverSyncedPeriodIsRequestedAsOneSpan() {
        val period = SyncPlanner.period(now, 7)
        assertEquals(listOf(period), SyncPlanner.spans(period, emptyList(), emptyList(), hour, now))
    }

    @Test
    fun aFullyCoveredPeriodOnlyAsksForTheRecentTail() {
        val period = SyncPlanner.period(now, 7)
        val covered = listOf(Span(period.startMs - day, now - 3 * hour))   // last synced three hours ago
        assertEquals(
            listOf(Span(now - 3 * hour, now)),   // the uncovered recent stretch swallows the one-hour tail
            SyncPlanner.spans(period, covered, emptyList(), hour, now),
        )
        val upToNow = listOf(Span(period.startMs - day, now))
        assertEquals(listOf(Span(now - hour, now)), SyncPlanner.spans(period, upToNow, emptyList(), hour, now))
    }

    @Test
    fun widerPeriodOnlyFetchesTheNewlyIncludedOlderPart() {
        val sevenDays = SyncPlanner.period(now, 7)
        val thirtyDays = SyncPlanner.period(now, 30)
        val covered = listOf(Span(sevenDays.startMs, now))
        assertEquals(
            listOf(Span(thirtyDays.startMs, sevenDays.startMs), Span(now - hour, now)),
            SyncPlanner.spans(thirtyDays, covered, emptyList(), hour, now),
        )
    }

    @Test
    fun nearbySpansAreCoalescedIntoOneRequest() {
        val period = SyncPlanner.period(now, 1)
        val covered = listOf(Span(period.startMs, now - 10 * hour), Span(now - 10 * hour + 10 * min, now))
        // A 10-minute hole is within the 30-minute join distance and the tail covers the end.
        assertEquals(listOf(Span(now - 10 * hour, now - 10 * hour + 10 * min), Span(now - hour, now)), SyncPlanner.spans(period, covered, emptyList(), hour, now))
        assertEquals(
            listOf(Span(0, 50 * min)),
            Intervals.merge(listOf(Span(0, 20 * min), Span(40 * min, 50 * min)), SyncPlanner.COALESCE_MS),
        )
    }

    @Test
    fun onlyRecentHolesInStoredDataAreAskedForAgain() {
        val period = SyncPlanner.period(now, 30)
        val stamps = listOf(
            now - 20 * day, now - 20 * day + 5 * min, now - 20 * day + 2 * hour,   // an old hole (ended 20 days ago)
            now - 2 * day, now - 2 * day + 5 * min, now - 2 * day + hour,            // a recent hole (ended 2 days ago)
            now - 2 * day + hour + 5 * min,
        )
        assertEquals(
            listOf(
                Span(now - 20 * day + 2 * hour, now - 2 * day),   // the long stretch before the recent readings ended 2 days ago
                Span(now - 2 * day + 5 * min, now - 2 * day + hour),
            ),
            SyncPlanner.recentGaps(stamps, period, now, SyncPlanner.GLUCOSE_GAP_MS),
        )
        // The hole that ended 20 days ago is not among them: it was asked for once and is trusted.
        assertTrue(SyncPlanner.recentGaps(stamps.take(3), period, now, SyncPlanner.GLUCOSE_GAP_MS).isEmpty())
    }

    @Test
    fun recentHolesOutsideThePeriodAreIgnoredAndOthersClamped() {
        val period = SyncPlanner.period(now, 1)
        val stamps = listOf(now - 3 * day, now - 3 * day + 2 * hour, now - day - hour, now - day + hour)
        assertEquals(
            listOf(Span(now - day, now - day + hour)),
            SyncPlanner.recentGaps(stamps, period, now, SyncPlanner.GLUCOSE_GAP_MS),
        )
    }

    @Test
    fun coverageFromRunsMarksStretchesWithoutHolesAsChecked() {
        val ts = listOf(100L, 200L, 300L, 5_000L, 5_100L)
        assertEquals(listOf(Span(99, 300), Span(4_999, 5_100)), SyncPlanner.coverageFromRuns(ts, 1_000L))
        assertTrue(SyncPlanner.coverageFromRuns(emptyList(), 1_000L).isEmpty())
        assertEquals(listOf(Span(41, 42)), SyncPlanner.coverageFromRuns(listOf(42L), 1_000L))
    }

    @Test
    fun manySpansAreSplitIntoQueriesOfAHundred() {
        val spans = (0 until 250).map { Span(it * 10L, it * 10L + 5) }
        assertEquals(listOf(100, 100, 50), SyncPlanner.chunks(spans).map { it.size })
    }

    @Test
    fun isoTextHasFixedWidthSoTextOrderIsTimeOrder() {
        assertEquals("2026-09-22T11:33:20.000Z", SyncPlanner.iso(java.time.Instant.parse("2026-09-22T11:33:20Z").toEpochMilli()))
        assertEquals("2026-09-22T11:33:20.050Z", SyncPlanner.iso(java.time.Instant.parse("2026-09-22T11:33:20.050Z").toEpochMilli()))
        assertTrue(SyncPlanner.iso(1_000L) < SyncPlanner.iso(2_000L))
    }

    @Test
    fun unsyncedAmountIgnoresTheLastDayAndTakesTheWorstSource() {
        val period = SyncPlanner.period(now, 7)
        val everything = listOf(Span(period.startMs - day, now))
        fun cov(vararg p: Pair<String, List<Span>>) = p.flatMap { (src, spans) -> spans.map { src to it } }
        assertEquals(0L, SyncPlanner.unsyncedMs(cov(Sources.GLUCOSE to everything, Sources.TREATMENTS to everything, Sources.IOB to everything), period))
        // Treatments were only fetched for the last 2 days; the settled part of the period is days 7 to 1 ago, so days 7 to 2 ago (5 days) are missing.
        val partial = cov(Sources.GLUCOSE to everything, Sources.TREATMENTS to listOf(Span(now - 2 * day, now)), Sources.IOB to everything)
        assertEquals(5 * day, SyncPlanner.unsyncedMs(partial, period))
        // Nothing ever synced: 6 settled days.
        assertEquals(6 * day, SyncPlanner.unsyncedMs(emptyList(), period))
    }
}
