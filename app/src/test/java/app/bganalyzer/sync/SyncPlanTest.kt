package app.bganalyzer.sync

import org.junit.Assert.assertEquals
import org.junit.Test

class SyncPlanTest {
    private val now = 1_790_000_000_000L

    @Test
    fun firstSyncFetchesNinetyDays() {
        assertEquals(now - 90L * 24 * 3600 * 1000, SyncPlan.fetchAfter(null, now))
    }

    @Test
    fun laterSyncsStartJustBeforeTheNewestReading() {
        assertEquals(now - 3_600_000L, SyncPlan.fetchAfter(now, now))
    }

    @Test
    fun treatmentCutoffIsFixedFormatIsoText() {
        // 2026-09-22T11:33:20.000Z minus one day when something is stored.
        val newest = java.time.Instant.parse("2026-09-22T11:33:20.000Z").toEpochMilli()
        assertEquals("2026-09-21T11:33:20.000Z", SyncPlan.treatmentsCreatedAfterIso(newest, now))
        // Milliseconds are always three digits, so text order matches time order.
        assertEquals("2026-09-21T11:33:20.050Z", SyncPlan.treatmentsCreatedAfterIso(newest + 50, now))
    }

    @Test
    fun firstTreatmentSyncFetchesNinetyDays() {
        val expected = java.time.Instant.ofEpochMilli(now - 90L * 24 * 3600 * 1000).toString()
        assertEquals(expected.substringBefore('.').substringBefore('Z'), SyncPlan.treatmentsCreatedAfterIso(null, now).substringBefore('.'))
    }
}
