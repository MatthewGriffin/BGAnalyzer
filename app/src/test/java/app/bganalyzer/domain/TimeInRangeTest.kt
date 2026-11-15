package app.bganalyzer.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class TimeInRangeTest {
    @Test
    fun emptyInputGivesZeroes() {
        val r = TimeInRange.of(emptyList())
        assertEquals(0, r.count)
        assertEquals(0.0, r.inRangePct, 0.0)
    }

    @Test
    fun readingsAreSplitAcrossRanges() {
        val r = TimeInRange.of(listOf(50.0, 60.0, 100.0, 150.0, 200.0, 300.0))
        assertEquals(1, r.veryLow); assertEquals(1, r.low); assertEquals(2, r.inRange)
        assertEquals(1, r.high); assertEquals(1, r.veryHigh)
        assertEquals(100.0, r.veryLowPct + r.lowPct + r.inRangePct + r.highPct + r.veryHighPct, 1e-9)
        assertEquals(860.0 / 6, r.meanMgdl, 1e-9)
    }

    @Test
    fun boundariesBelongToTheDocumentedSide() {
        val r = TimeInRange.of(listOf(54.0, 70.0, 180.0, 250.0, 250.1))
        assertEquals(0, r.veryLow)   // 54 is low, not very low
        assertEquals(1, r.low)
        assertEquals(2, r.inRange)   // 70 and 180 are in range
        assertEquals(1, r.high)      // 250 is high, not very high
        assertEquals(1, r.veryHigh)
    }

    @Test
    fun rangesMustBeIncreasing() {
        assertThrows(IllegalArgumentException::class.java) { GlucoseRanges(lowBelow = 200.0) }
    }
}
