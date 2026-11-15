package app.bganalyzer.domain

import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

class BasalComparisonTest {
    private val zone = ZoneId.of("Europe/London")
    private val min = 60_000L
    private fun ms(d: LocalDate, h: Int = 0, m: Int = 0) = d.atTime(h, m).atZone(zone).toInstant().toEpochMilli()
    private val day1 = LocalDate.of(2026, 9, 1)

    private fun temp(startMs: Long, rate: Double, durMin: Int, valid: Boolean = true) =
        TreatmentEntity("t$startMs", startMs, "Temp Basal", null, null, false, rate, durMin * min, null, valid, null, "{}")

    private fun profile(startMs: Long, vararg steps: Pair<Int, Double>) = ProfileEntity(
        "p$startMs", startMs, "main", "mmol", "Europe/London",
        """{"defaultProfile":"main","store":{"main":{"basal":[${steps.joinToString(",") { """{"time":"x","timeAsSeconds":${it.first},"value":${it.second}}""" }}]}}}""",
    )

    /** Back-to-back 30-minute temp basals covering [days] local days from [first], with the rate chosen by local hour. */
    private fun loop(first: LocalDate, days: Int, rate: (Int) -> Double): List<TreatmentEntity> {
        val start = ms(first)
        val end = ms(first.plusDays(days.toLong()))
        return generateSequence(start) { it + 30 * min }.takeWhile { it < end }.map { temp(it, rate(TimeBlocks.localHour(it, zone)), 30) }.toList()
    }

    private val flat = profile(0, 0 to 1.0)

    @Test
    fun aLoopThatRunsHighAllDayIsAboveProfileAllTheTime() {
        val r = BasalComparison.analyze(loop(day1, 6) { 1.5 }, listOf(flat), ms(day1), ms(day1.plusDays(6)), zone, 6)
        assertEquals(100.0, r.overall.abovePct, 1e-9); assertEquals(0.0, r.overall.belowPct, 1e-9)
        assertEquals(1.5, r.overall.avgActual, 1e-9); assertEquals(1.0, r.overall.avgScheduled, 1e-9); assertEquals(50.0, r.overall.changePct, 1e-9)
        assertEquals(6, r.overall.days); assertEquals(100.0, r.loopCoveragePct, 1e-9)
        assertTrue(r.blocks.all { it.enoughDays && it.abovePct == 100.0 })
    }

    @Test
    fun rateAndSplitDependOnTheTimeOfDay() {
        // Suspended overnight (below profile, 0 U/h), at profile in the morning, above profile in the evening.
        val r = BasalComparison.analyze(loop(day1, 6) { h -> if (h < 6) 0.0 else if (h < 18) 1.0 else 1.4 }, listOf(flat), ms(day1), ms(day1.plusDays(6)), zone, 6)
        assertEquals(100.0, r.blocks[0].belowPct, 1e-9); assertEquals(100.0, r.blocks[0].zeroPct, 1e-9)
        assertEquals(100.0, r.blocks[1].atPct, 1e-9); assertEquals(100.0, r.blocks[2].atPct, 1e-9)
        assertEquals(100.0, r.blocks[3].abovePct, 1e-9)
        assertEquals(25.0, r.overall.zeroPct, 1e-9); assertEquals(25.0, r.overall.abovePct, 1e-9); assertEquals(50.0, r.overall.atPct, 1e-9)
        assertEquals((0.0 + 1.0 + 1.0 + 1.4) / 4, r.overall.avgActual, 1e-9)
    }

    @Test
    fun smallDifferencesBelowHalfAPumpStepCountAsAtProfile() {
        val r = BasalComparison.analyze(loop(day1, 5) { 1.02 }, listOf(flat), ms(day1), ms(day1.plusDays(5)), zone, 6)
        assertEquals(100.0, r.overall.atPct, 1e-9)
    }

    @Test
    fun timeWithoutATempBasalIsExcludedAndReportedAsMissingLoopData() {
        // The loop only ran in the first half of each day.
        val half = (0 until 6).flatMap { d -> (0 until 24).map { temp(ms(day1.plusDays(d.toLong()), 0) + it * 30 * min, 1.5, 30) } }
        val r = BasalComparison.analyze(half, listOf(flat), ms(day1), ms(day1.plusDays(6)), zone, 6)
        assertEquals(50.0, r.loopCoveragePct, 1e-9)
        assertEquals(100.0, r.overall.abovePct, 1e-9)           // percentages are of the covered time only
        assertEquals(0, r.blocks[2].days); assertEquals(0, r.blocks[3].days)   // no loop data in the afternoon or evening
        assertEquals(6, r.blocks[0].days)
    }

    @Test
    fun theProfileInEffectAtEachMomentIsUsed() {
        val first = LocalDate.of(2026, 9, 1)
        val newProfile = profile(ms(first.plusDays(3)), 0 to 2.0)
        val r = BasalComparison.analyze(loop(first, 6) { 1.5 }, listOf(flat, newProfile), ms(first), ms(first.plusDays(6)), zone, 24 / 4)
        assertEquals(50.0, r.overall.abovePct, 1e-9)            // above the old 1.0 for 3 days, below the new 2.0 for 3 days
        assertEquals(50.0, r.overall.belowPct, 1e-9)
        assertEquals(1.5, r.overall.avgScheduled, 1e-9)
    }

    @Test
    fun theLongDayWhenClocksGoBackKeepsItsRealLength() {
        val d = LocalDate.of(2026, 10, 25)   // 25 hours in London
        val r = BasalComparison.analyze(loop(d, 1) { 1.0 }, listOf(flat), ms(d), ms(d.plusDays(1)), zone, 6)
        assertEquals(100.0, r.loopCoveragePct, 1e-9)
        assertEquals(1, r.blocks[0].days)       // the 00:00-06:00 block holds 7 real hours and still counts as one day
    }

    @Test
    fun individualTempBasalsAreCountedAgainstTheSchedule() {
        val temps = listOf(temp(ms(day1, 1), 1.5, 30), temp(ms(day1, 2), 0.0, 30), temp(ms(day1, 3), 1.0, 30), temp(ms(day1, 4), 2.0, 0), temp(ms(day1, 5), 1.5, 30, valid = false))
        val r = BasalComparison.analyze(temps, listOf(flat), ms(day1), ms(day1.plusDays(1)), zone, 6)
        assertEquals(3, r.tempCount); assertEquals(1, r.tempAbove); assertEquals(1, r.tempBelow); assertEquals(1, r.tempAt)
    }

    @Test
    fun withoutAProfileNothingCanBeCompared() {
        val r = BasalComparison.analyze(loop(day1, 5) { 1.5 }, emptyList(), ms(day1), ms(day1.plusDays(5)), zone, 6)
        assertEquals(0.0, r.loopCoveragePct, 0.0); assertEquals(0, r.overall.days); assertEquals(0, r.tempCount)
    }
}
