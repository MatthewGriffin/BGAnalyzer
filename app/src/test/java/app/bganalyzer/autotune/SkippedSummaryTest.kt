package app.bganalyzer.autotune

import org.junit.Assert.assertEquals
import org.junit.Test

class SkippedSummaryTest {
    @Test fun consecutiveDaysWithTheSameReasonBecomeOneLine() {
        val s = listOf("2026-11-01", "2026-11-02", "2026-11-03").map { SkippedDay(it, "no insulin records") } +
            SkippedDay("2026-11-05", "no insulin records") + SkippedDay("2026-11-06", "marked as bad data")
        assertEquals(
            listOf("2026-11-01 to 2026-11-03: no insulin records", "2026-11-05: no insulin records", "2026-11-06: marked as bad data"),
            SkippedSummary.lines(s),
        )
    }
}
