package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.TreatmentEntity
import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime

class FastingDriftTest {
    private val zone = ZoneId.of("UTC")
    private val start = ZonedDateTime.of(2026, 1, 1, 0, 0, 0, 0, zone).toInstant().toEpochMilli()
    private fun day(d: Int, startMgdl: Double, perHour: Double) = (0 until 72).map {
        reading(start + d * 86_400_000L + it * 300_000L, startMgdl + perHour * it / 12.0)
    }
    private fun reading(t: Long, v: Double) = GlucoseReadingEntity(t, v)

    @Test fun measuresRisingSlopeOnQuietDays() {
        val readings = (0 until 6).flatMap { day(it, 100.0, 10.0) }
        val d = FastingDrift.analyze(readings, emptyList(), zone, 6)[0]
        assertEquals(6, d.days); assertEquals(10.0, d.medianSlopeMgdlPerHour, 0.01); assertEquals(6, d.risingDays)
    }

    @Test fun carbsBreakTheQuietWindow() {
        val readings = day(0, 100.0, 10.0)
        val carb = TreatmentEntity("c", start - 3_600_000L, "Carb Correction", null, 20.0, false, null, null, null, true, null, "{}")
        assertEquals(0, FastingDrift.analyze(readings, listOf(carb), zone, 6)[0].days)
    }
}
