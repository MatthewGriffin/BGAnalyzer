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
}
