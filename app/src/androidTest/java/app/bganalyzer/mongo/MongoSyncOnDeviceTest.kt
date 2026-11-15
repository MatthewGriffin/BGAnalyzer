package app.bganalyzer.mongo

import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.sync.NightscoutSync
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNotNull
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Syncs from a throwaway MongoDB that has been seeded with Nightscout-shaped collections (see HANDOFF) into an
 * in-memory Room database: `-Pandroid.testInstrumentationRunnerArguments.syncMongoUri=mongodb://...` and `syncMongoDb=seed`.
 * Never point it at the real Nightscout database (it only reads, but there is no reason to).
 */
@RunWith(AndroidJUnit4::class)
class MongoSyncOnDeviceTest {
    @Test
    fun syncsSeededCollectionsIntoRoom() = runBlocking {
        val args = InstrumentationRegistry.getArguments()
        val uri = args.getString("syncMongoUri")
        assumeNotNull(uri)
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(ctx, AppDatabase::class.java).build()
        try {
            val result = NightscoutSync(db).run(uri!!, args.getString("syncMongoDb") ?: "seed", 2)
            val stored = db.glucoseReadingDao().timestampsSince(0).size
            assertTrue("a 2 day period holds about 576 of the 600 seeded entries, got $stored", stored in 570..576)
            assertEquals(1, result.treatmentsFetched)
            assertEquals(1, result.iobFetched)
            assertTrue(db.profileDao().all().isNotEmpty())
        } finally {
            db.close()
        }
    }
}
