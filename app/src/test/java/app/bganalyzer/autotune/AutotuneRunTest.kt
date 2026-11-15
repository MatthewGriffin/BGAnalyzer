package app.bganalyzer.autotune

import app.bganalyzer.domain.BasalSegment
import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneId

class AutotuneRunTest {
    private val zone = ZoneId.of("UTC")
    private val hour = 3_600_000L
    private val day = 24 * hour
    private val baseline = AtProfile(List(24) { 1.0 }, 100.0, 10.0)
    // 2026-11-01 00:00 UTC, so the run below ends 2026-11-08 04:00
    private val origin = 1_793_491_200_000L
    private val end = origin + 7 * day + 4 * hour

    private fun data(daysCovered: Int, glucose: (Long) -> Double) = AutotuneData(
        readings = (0 until daysCovered * 288 + 288).map { AtReading(origin + it * 300_000L, glucose(origin + it * 300_000L)) },
        // a tiny bolus every day stands for "the pump was running": days without insulin records are skipped
        boluses = (0..daysCovered).map { Dose(origin + it * day + 12 * hour, 0.01) }, meals = emptyList(),
        basalBetween = { f, t -> listOf(BasalSegment(f, t, 1.0, true)) },
    )

    @Test fun defaultEndIsTheLastFourAmBeforeNow() {
        val now = origin + 10 * hour // 10:00
        assertEquals(origin + 4 * hour, AutotuneRun.defaultEnd(now, zone))
        assertEquals(origin - day + 4 * hour, AutotuneRun.defaultEnd(origin + 2 * hour, zone)) // 02:00 is before 04:00
    }

    @Test fun steadyGlucoseWithMatchingBasalLeavesTheProfileAlone() {
        val r = AutotuneRun.run(data(8) { 110.0 }, baseline, AutotuneLimits(), zone, end, 7)
        assertEquals(7, r.daysTuned); assertTrue(r.skipped.isEmpty())
        r.tuned.basal.forEach { assertEquals(1.0, it, 1e-9) }
        assertEquals(baseline.isf, r.tuned.isf, 1e-9)
    }

    @Test fun glucoseRisingAllDayRaisesBasalButNotBeyondTheAutosensLimit() {
        // +2 mg/dL every 5 minutes with no insulin effect: deviations are positive
        val r = AutotuneRun.run(data(8) { 110.0 + ((it - origin) / 300_000L) % 30 * 2 }, baseline, AutotuneLimits(autosensMax = 1.2), zone, end, 7)
        assertTrue(r.tuned.basal.sum() > 24.0)
        r.tuned.basal.forEach { assertTrue(it <= 1.2 + 1e-9) }
    }

    @Test fun excludedAndEmptyDaysAreSkippedAndReported() {
        val r = AutotuneRun.run(data(8) { 110.0 }, baseline, AutotuneLimits(), zone, end, 7, skipDate = { it == "2026-11-02" })
        assertEquals(6, r.daysTuned)
        assertEquals(listOf("2026-11-02"), r.skipped.map { it.date })
        val none = AutotuneRun.run(AutotuneData(emptyList(), emptyList(), emptyList()) { f, t -> listOf(BasalSegment(f, t, 1.0, true)) }, baseline, AutotuneLimits(), zone, end, 3)
        assertEquals(0, none.daysTuned); assertEquals(3, none.skipped.size)
        assertEquals(baseline, none.tuned)
    }
}

class AutotuneAdvisorTest {
    private val zone = ZoneId.of("UTC")
    private fun result(tunedHour3: Double) = AutotuneResult(
        AtProfile(List(24) { 1.0 }, 100.0, 10.0),
        AtProfile(List(24) { if (it == 3) tunedHour3 else 1.0 }, 100.0, 10.0),
        7, emptyList(), emptyList(),
    )

    @Test fun anIncreaseIsHeldInAnHourWithLows() {
        val readings = (0 until 7).flatMap { d -> listOf(AtReading(d * 86_400_000L + 3 * 3_600_000L, 60.0), AtReading(d * 86_400_000L + 3 * 3_600_000L + 300_000L, 100.0)) }
        val a = AutotuneAdvisor.advise(result(1.15), readings, zone).hours[3]
        assertEquals(1.0, a.suggested, 0.0); assertNotNull(a.heldReason)
    }

    @Test fun aDecreaseIsNeverHeldAndAnIncreaseWithoutLowsPasses() {
        val readings = (0 until 7).map { AtReading(it * 86_400_000L + 3 * 3_600_000L, 100.0) }
        assertEquals(0.9, AutotuneAdvisor.advise(result(0.9), readings.map { it.copy(mgdl = 50.0) }, zone).hours[3].suggested, 0.0)
        assertEquals(1.15, AutotuneAdvisor.advise(result(1.15), readings, zone).hours[3].suggested, 0.0)
    }
}

class NoInsulinDayTest {
    private val zone = ZoneId.of("UTC")
    private val hour = 3_600_000L
    private val day = 24 * hour
    private val origin = 1_793_491_200_000L

    @Test fun aDayWithNoInsulinRecordsIsSkipped() {
        val d = AutotuneData(
            readings = (0 until 9 * 288).map { AtReading(origin + it * 300_000L, 110.0) },
            boluses = listOf(Dose(origin + 2 * day + 12 * hour, 0.01)), // only one day has insulin
            meals = emptyList(), basalBetween = { f, t -> listOf(BasalSegment(f, t, 1.0, true)) },
        )
        val r = AutotuneRun.run(d, AtProfile(List(24) { 1.0 }, 100.0, 10.0), AutotuneLimits(), zone, origin + 7 * day + 4 * hour, 7)
        assertEquals(1, r.daysTuned)
        assertTrue(r.skipped.all { it.reason.startsWith("no insulin records") })
    }
}
