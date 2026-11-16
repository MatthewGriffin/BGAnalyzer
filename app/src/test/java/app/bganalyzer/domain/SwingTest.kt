package app.bganalyzer.domain

import org.junit.Assert.*
import org.junit.Test

class SwingTest {
    private val five = 300_000L
    private fun series(n: Int, f: (Int) -> Double) = LongArray(n) { it * five } to DoubleArray(n) { f(it) }

    @Test fun aFlatLineAndASteadyHeartMonitorBothAreFullyInRangeButOnlyOneSwings() {
        // 100% in range both, same mean (6.5 mmol/L = 117 mg/dL): flat, and a 4 to 9 mmol/L sawtooth with a 2 hour period
        val (t, flat) = series(288) { 117.0 }
        val (_, saw) = series(288) { i -> val phase = (i % 24) / 24.0; 72.0 + 90.0 * (if (phase < 0.5) phase * 2 else 2 - phase * 2) }
        val flatSwing = Swing.of(t, flat).perHour!!
        val sawSwing = Swing.of(t, saw).perHour!!
        assertEquals(0.0, flatSwing, 1e-9)
        assertTrue("sawtooth swing $sawSwing", sawSwing > 40.0) // about 2.5 mmol/L per hour or more
        val flatTir = TimeInRange.of(flat.toList()); val sawTir = TimeInRange.of(saw.toList())
        assertEquals(100.0, flatTir.inRangePct, 0.01); assertEquals(100.0, sawTir.inRangePct, 0.01)
        // CV records why it was not enough: the sawtooth is "stable" by the 36% consensus figure
        assertTrue("sawtooth CV ${sawTir.cvPct}", sawTir.cvPct < 36.0)
        assertEquals(0.0, flatTir.cvPct, 1e-9)
    }

    @Test fun aGapInTheDataAddsNoSwing() {
        // 100 mg/dL for 2 hours, no readings for 6 hours, then 200 mg/dL: the jump across the gap is not a swing
        val times = (0 until 24).map { it * five } + (96 until 120).map { it * five }
        val values = List(24) { 100.0 } + List(24) { 200.0 }
        val s = Swing.of(times.toLongArray(), values.toDoubleArray())
        assertEquals(0.0, s.perHour!!, 1e-9)
    }

    @Test fun sensorJitterBetweenFiveMinuteReadingsIsNotCounted() {
        // alternates 100, 104 every 5 minutes (noise): steps are 15 minutes apart so each step sees 4 or 0
        val (t, v) = series(288) { if (it % 2 == 0) 100.0 else 104.0 }
        val perHour = Swing.of(t, v).perHour!!
        assertTrue("jitter swing $perHour", perHour <= 16.0) // 4 mg/dL over 15 minutes at most, not 4 mg/dL every 5 minutes
    }

    @Test fun nothingMeasuredIsNull() {
        assertNull(Swing.of(LongArray(1), DoubleArray(1)).perHour)
    }
}
