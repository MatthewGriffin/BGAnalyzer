package app.bganalyzer.data

import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

/** Runs the real delete queries on a throwaway in-memory database. */
@RunWith(AndroidJUnit4::class)
class RetentionTest {
    private val day = 24L * 60 * 60 * 1000
    private val now = 1_800_000_000_000L

    private fun treatment(id: String, ageDays: Int, type: String, raw: String = "{}") =
        TreatmentEntity(id, now - ageDays * day, type, null, null, false, null, null, null, true, null, raw)

    @Test
    fun oldDataGoesButProfileSwitchesAndRecentDataStay() = runBlocking {
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(ctx, AppDatabase::class.java).build()
        try {
            db.glucoseReadingDao().upsertAll(listOf(GlucoseReadingEntity(now - 200 * day, 100.0), GlucoseReadingEntity(now - 10 * day, 100.0)))
            db.iobDao().upsertAll(listOf(IobSampleEntity("a", now - 200 * day, 1.0, null, null, null), IobSampleEntity("b", now - 5 * day, 1.0, null, null, null)))
            db.treatmentDao().upsertAll(listOf(
                treatment("old-bolus", 200, "Correction Bolus"),
                treatment("old-switch", 200, "Profile Switch"),
                treatment("old-effective", 200, "Note", "{\"profileJson\":\"x\"}"),
                treatment("old-note", 200, "Note", "{\"notes\":\"hello\"}"),
                treatment("new-bolus", 3, "Correction Bolus"),
            ))
            db.coverageDao().insertAll(listOf(CoverageEntity("glucose", now - 300 * day, now - 150 * day), CoverageEntity("glucose", now - 50 * day, now)))

            val deleted = Retention.prune(db, now)

            assertEquals(4, deleted) // 1 reading + 1 iob + 2 treatments
            assertEquals(1, db.glucoseReadingDao().all().size)
            assertEquals(1, db.iobDao().all().size)
            assertEquals(setOf("old-switch", "old-effective", "new-bolus"), db.treatmentDao().all().map { it.id }.toSet())
            assertEquals(1, db.coverageDao().forSource("glucose").size)
        } finally {
            db.close()
        }
    }
}
