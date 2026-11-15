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
}
