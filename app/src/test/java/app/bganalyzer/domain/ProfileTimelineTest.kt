package app.bganalyzer.domain

import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

/** Records follow the shapes AAPS uploads (see reference/aaps/ProfileSwitchExtension.kt), with made-up values. */
class ProfileTimelineTest {
    private val zone = ZoneId.of("Europe/London")
    private val day = LocalDate.of(2026, 9, 1)
    private fun at(h: Int, m: Int = 0, d: LocalDate = day) = d.atTime(h, m).atZone(zone).toInstant().toEpochMilli()
    private val min = 60_000L

    private fun profileJson(low: Double, high: Double) =
        """{\"units\":\"mmol\",\"basal\":[{\"time\":\"00:00\",\"timeAsSeconds\":0,\"value\":$low},{\"time\":\"06:00\",\"timeAsSeconds\":21600,\"value\":$high}]}"""

    private fun switchRecord(ts: Long, name: String = "main", pct: Int = 100, shift: String = "0", durMin: Int = 0, low: Double = 1.0, high: Double = 2.0, valid: Boolean = true) =
        TreatmentEntity(
            "ps$ts", ts, "Profile Switch", null, null, false, null, null, null, valid, null,
            """{"eventType":"Profile Switch","profile":"$name","originalProfileName":"$name","percentage":$pct,"timeshift":$shift,"duration":$durMin,"originalDuration":${durMin * 60_000L},"profileJson":"${profileJson(low, high)}"}""",
        )

    private fun effectiveRecord(ts: Long, name: String = "main", pct: Int = 100, low: Double, high: Double, durMs: Long = 0, id: String = "eps$ts") =
        TreatmentEntity(
            id, ts, "Note", null, null, false, null, null, null, true, null,
            """{"eventType":"Note","originalProfileName":"$name","originalPercentage":$pct,"originalTimeshift":0,"originalDuration":$durMs,"profileJson":"${profileJson(low, high)}"}""",
        )

    private fun resolver(events: List<TreatmentEntity>, uploaded: List<ProfileEntity> = emptyList()) =
        ProfileResolver(ProfileTimeline.entries(events), uploaded)

    private fun uploaded(startMs: Long, low: Double, high: Double) = ProfileEntity(
        "p$startMs", startMs, "main", "mmol", "Europe/London",
        """{"defaultProfile":"main","store":{"main":{"basal":[{"time":"00:00","timeAsSeconds":0,"value":$low},{"time":"06:00","timeAsSeconds":21600,"value":$high}]}}}""",
    )

    @Test
    fun aSwitchAloneHasItsPercentageApplied() {
        val r = resolver(listOf(switchRecord(at(0), pct = 110)))
        assertEquals(1.1, r.basalAt(at(3), zone)!!, 1e-9)
        assertEquals(2.2, r.basalAt(at(7), zone)!!, 1e-9)
    }

    @Test
    fun theEffectiveRecordIsUsedAsIsSoTheModifierIsNotAppliedTwice() {
        val events = listOf(switchRecord(at(0), pct = 110), effectiveRecord(at(0, 1), pct = 110, low = 1.1, high = 2.2))
        val entries = ProfileTimeline.entries(events)
        assertEquals(1, entries.size)                       // the pair is one change, not two
        assertEquals(EffectiveProfile.Source.EFFECTIVE_RECORD, entries[0].source)
        assertEquals(2.2, ProfileResolver(entries, emptyList()).basalAt(at(7), zone)!!, 1e-9)   // not 2.42
    }

    @Test
    fun aTimeShiftMovesTheSchedule() {
        // +2 h: the 06:00 step now starts at 08:00.
        val r = resolver(listOf(switchRecord(at(0), shift = "2")))
        assertEquals(1.0, r.basalAt(at(7), zone)!!, 1e-9)
        assertEquals(2.0, r.basalAt(at(8, 30), zone)!!, 1e-9)
        assertEquals(2.0, r.basalAt(at(1), zone)!!, 1e-9)    // before 02:00 the previous day's last step still runs
    }

    @Test
    fun aShiftUploadedInMillisecondsIsReadAsHours() {
        val e = ProfileTimeline.entries(listOf(switchRecord(at(0), shift = "7200000")))
        assertEquals(2, e.single().timeshiftHours)
    }

    @Test
    fun aTemporarySwitchEndsAndThePreviousProfileResumes() {
        val r = resolver(listOf(switchRecord(at(8), pct = 100), switchRecord(at(10), pct = 50, durMin = 60)))
        assertEquals(2.0, r.basalAt(at(9), zone)!!, 1e-9)
        assertEquals(1.0, r.basalAt(at(10, 30), zone)!!, 1e-9)   // 50% of 2.0
        assertEquals(2.0, r.basalAt(at(11, 30), zone)!!, 1e-9)   // back to the 100% profile
    }

    @Test
    fun theLatestSwitchWinsAndEditsBetweenSwitchesAreNotApplied() {
        val switchTime = at(0)
        val editedLater = uploaded(at(0, 0, day.plusDays(2)), 9.0, 9.0)        // uploaded edit, never switched to
        val r = resolver(listOf(switchRecord(switchTime, low = 1.0, high = 2.0)), listOf(uploaded(0, 5.0, 5.0), editedLater))
        assertEquals(2.0, r.basalAt(at(7, 0, day.plusDays(3)), zone)!!, 1e-9)
    }

    @Test
    fun beforeAnySwitchTheUploadedProfileIsUsed() {
        val r = resolver(listOf(switchRecord(at(0, 0, day.plusDays(5)))), listOf(uploaded(0, 5.0, 6.0)))
        assertEquals(6.0, r.basalAt(at(7), zone)!!, 1e-9)
        assertNull(resolver(emptyList()).basalAt(at(7), zone))
    }

    @Test
    fun anEffectiveRecordWithoutItsSwitchStillCountsAsAChange() {
        val e = ProfileTimeline.entries(listOf(effectiveRecord(at(9), pct = 80, low = 0.8, high = 1.6)))
        assertEquals(1, e.size); assertEquals(80, e[0].percentage)
        assertEquals(1.6, ProfileResolver(e, emptyList()).basalAt(at(10), zone)!!, 1e-9)
    }

    @Test
    fun invalidSwitchesAreIgnoredAndChangesAreFilteredByTime() {
        val events = listOf(switchRecord(at(1), valid = false), switchRecord(at(2)), switchRecord(at(5), name = "sport", pct = 120))
        val r = resolver(events)
        assertEquals(listOf("main", "sport"), r.changes(at(0), at(23)).map { it.name })
        assertEquals(listOf("sport"), r.changes(at(3), at(23)).map { it.name })
    }

    @Test
    fun labelsDescribeTheModifier() {
        val plain = ProfileTimeline.entries(listOf(switchRecord(at(0)))).single()
        assertEquals("main", plain.label())
        val mod = ProfileTimeline.entries(listOf(switchRecord(at(0), pct = 110, shift = "2", durMin = 60))).single()
        assertEquals("main 110% +2h (60 min)", mod.label())
        assertTrue(mod.hasModifier && mod.isTemporary)
    }

    @Test
    fun scheduledStretchesOnTheChartFollowTheActiveProfile() {
        val r = resolver(listOf(switchRecord(at(0), pct = 100), switchRecord(at(8), pct = 200)))
        val seg = BasalTimeline.build(emptyList(), r, at(7), at(9), zone)
        assertEquals(listOf(BasalSegment(at(7), at(8), 2.0, true), BasalSegment(at(8), at(9), 4.0, true)), seg)
    }
}
