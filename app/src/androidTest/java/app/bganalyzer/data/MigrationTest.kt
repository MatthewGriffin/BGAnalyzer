package app.bganalyzer.data

import androidx.room.testing.MigrationTestHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Pins that upgrading the database keeps the user's saved data. It builds throwaway databases with their own
 * names, so it never touches the app's real database. Add a test per new version; never edit an old one.
 */
@RunWith(AndroidJUnit4::class)
class MigrationTest {
    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        AppDatabase::class.java,
        emptyList(),
        FrameworkSQLiteOpenHelperFactory(),
    )

    @Test
    fun version1To2KeepsReadingsAndAddsTheNewTables() {
        helper.createDatabase("migration-test-v1", 1).apply {
            execSQL("INSERT INTO glucose_readings (timestampMs, mgdl) VALUES (1000, 5.5), (2000, 120.0)")
            close()
        }
        val db = helper.runMigrationsAndValidate("migration-test-v1", 2, true)
        db.query("SELECT timestampMs, mgdl FROM glucose_readings ORDER BY timestampMs").use { c ->
            assertEquals(2, c.count)
            c.moveToFirst(); assertEquals(1000L, c.getLong(0)); assertEquals(5.5, c.getDouble(1), 0.0)
            c.moveToNext(); assertEquals(2000L, c.getLong(0)); assertEquals(120.0, c.getDouble(1), 0.0)
        }
        db.query("SELECT COUNT(*) FROM treatments").use { c -> c.moveToFirst(); assertEquals(0, c.getInt(0)) }
        db.query("SELECT COUNT(*) FROM profiles").use { c -> c.moveToFirst(); assertEquals(0, c.getInt(0)) }
    }

    @Test
    fun version2To3KeepsAllSavedDataAndAddsTheNewTables() {
        helper.createDatabase("migration-test-v2", 2).apply {
            execSQL("INSERT INTO glucose_readings (timestampMs, mgdl) VALUES (1000, 5.5), (2000, 120.0)")
            execSQL(
                "INSERT INTO treatments (id, timestampMs, eventType, insulin, carbs, isSmb, rateUph, durationMs, percentage, valid, srvModifiedMs, rawJson) " +
                    "VALUES ('t1', 1500, 'Meal Bolus', 2.5, 30.0, 0, NULL, NULL, NULL, 1, NULL, '{}')",
            )
            execSQL("INSERT INTO profiles (id, startMs, defaultProfile, units, timezone, rawJson) VALUES ('p1', 10, 'main', 'mmol', 'Europe/London', '{}')")
            close()
        }
        val db = helper.runMigrationsAndValidate("migration-test-v2", 3, true)
        db.query("SELECT COUNT(*) FROM glucose_readings").use { c -> c.moveToFirst(); assertEquals(2, c.getInt(0)) }
        db.query("SELECT carbs FROM treatments WHERE id = 't1'").use { c -> c.moveToFirst(); assertEquals(30.0, c.getDouble(0), 0.0) }
        db.query("SELECT timezone FROM profiles WHERE id = 'p1'").use { c -> c.moveToFirst(); assertEquals("Europe/London", c.getString(0)) }
        db.query("SELECT COUNT(*) FROM iob_samples").use { c -> c.moveToFirst(); assertEquals(0, c.getInt(0)) }
        db.query("SELECT COUNT(*) FROM sync_coverage").use { c -> c.moveToFirst(); assertEquals(0, c.getInt(0)) }
    }
}
