package app.bganalyzer.rest

import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.sync.NightscoutSync
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNotNull
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Syncs a short period from a real Nightscout site over REST into a throwaway in-memory database. Local only, needs
 * internet: `-Pandroid.testInstrumentationRunnerArguments.restUrl=https://your-site.example`. Read-only on the site.
 */
@RunWith(AndroidJUnit4::class)
class RestSyncOnDeviceTest {
    @Test
    fun syncsAFewDaysIntoRoom() = runBlocking {
        val url = InstrumentationRegistry.getArguments().getString("restUrl")
        assumeNotNull(url)
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(ctx, AppDatabase::class.java).build()
        try {
            val result = RestSyncSource(url!!, RestAuth.None).use { NightscoutSync(db).run(it, 3) }
            assertTrue("glucose fetched", result.glucoseFetched > 0)
            assertTrue("readings stored", db.glucoseReadingDao().timestampsSince(0).isNotEmpty())
            assertTrue("profiles stored", db.profileDao().all().isNotEmpty())
        } finally {
            db.close()
        }
    }
}
