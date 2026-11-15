package app.bganalyzer.domain

import org.junit.Assert.*
import org.junit.Test

class ProfileChangesTest {
    private fun steps(vararg r: Double) = r.mapIndexed { i, v -> BasalStep(i * 3600, v) }
    private fun p(start: Long, basal: List<BasalStep>, duration: Long = 0, settings: ProfileSettings = ProfileSettings.NONE) =
        EffectiveProfile(start, "main", 100, 0, duration, basal, EffectiveProfile.Source.EFFECTIVE_RECORD, settings)
    private val flat = List(24) { BasalStep(it * 3600, 1.0) }

    @Test fun switchingToTheSameSettingsAgainIsNotAChange() {
        val e = listOf(p(1000, flat), p(2000, flat), p(3000, flat))
        assertNull(ProfileChanges.lastRealChange(e, 10_000))
    }

    @Test fun aTemporarySwitchIsNotAChange() {
        val e = listOf(p(1000, flat), p(2000, List(24) { BasalStep(it * 3600, 0.8) }, duration = 3_600_000))
        assertNull(ProfileChanges.lastRealChange(e, 10_000))
        assertEquals(1000L, ProfileChanges.baseline(e, 10_000)!!.startMs)
    }

    @Test fun movingBasalBetweenHoursWithTheSameDailyTotalIsAChange() {
        val moved = List(24) { BasalStep(it * 3600, if (it == 3) 1.5 else if (it == 4) 0.5 else 1.0) }
        val e = listOf(p(1000, flat), p(2000, moved))
        assertEquals(2000L, ProfileChanges.lastRealChange(e, 10_000)!!.startMs)
    }

    @Test fun aChangeOnlyInSensitivityOrCarbRatioIsAChange() {
        val a = ProfileSettings(listOf(BasalStep(0, 50.0)), listOf(BasalStep(0, 10.0)), 6.0)
        val isf = ProfileSettings(listOf(BasalStep(0, 45.0)), listOf(BasalStep(0, 10.0)), 6.0)
        val cr = ProfileSettings(listOf(BasalStep(0, 50.0)), listOf(BasalStep(0, 9.0)), 6.0)
        assertNotNull(ProfileChanges.lastRealChange(listOf(p(1, flat, settings = a), p(2, flat, settings = isf)), 10))
        assertNotNull(ProfileChanges.lastRealChange(listOf(p(1, flat, settings = a), p(2, flat, settings = cr)), 10))
    }

    @Test fun theLatestRealChangeIsReturnedAndFutureEntriesAreIgnored() {
        val other = List(24) { BasalStep(it * 3600, 1.2) }
        val e = listOf(p(1000, flat), p(2000, other), p(3000, other), p(9000, flat))
        assertEquals(2000L, ProfileChanges.lastRealChange(e, 5000)!!.startMs)
        assertEquals(9000L, ProfileChanges.lastRealChange(e, 10_000)!!.startMs)
    }
}
