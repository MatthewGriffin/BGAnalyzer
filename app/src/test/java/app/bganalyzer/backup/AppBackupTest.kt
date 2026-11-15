package app.bganalyzer.backup

import app.bganalyzer.data.GlucoseReadingEntity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

class AppBackupTest {
    private val pass = "correct horse"
    private fun reading(t: Long, v: Double = 100.0) = GlucoseReadingEntity(t, v)

    private fun backupOf(dao: FakeDao, settings: FakeSettings): ByteArray = runBlocking {
        ByteArrayOutputStream().also { AppBackup(dao, settings, nowMs = { 5L }).export(it, pass) }.toByteArray()
    }

    @Test
    fun restoreIntoAnEmptyAppBringsEverythingBack() = runBlocking {
        val file = backupOf(FakeDao(listOf(reading(1), reading(2, 150.0))), FakeSettings("mongodb://u:p@h/db", "db"))
        val dao = FakeDao(); val settings = FakeSettings()
        val result = AppBackup(dao, settings).restore(ByteArrayInputStream(file), pass)
        assertEquals(RestoreResult(2, true), result)
        assertEquals(listOf(reading(1), reading(2, 150.0)), dao.all())
        assertEquals("mongodb://u:p@h/db", settings.uri); assertEquals("db", settings.database)
    }

    @Test
    fun restoreMergesAndNeverDeletesExistingReadings() = runBlocking {
        val file = backupOf(FakeDao(listOf(reading(1), reading(2))), FakeSettings("mongodb://h/db", "db"))
        val dao = FakeDao(listOf(reading(2, 999.0 - 800), reading(3)))
        AppBackup(dao, FakeSettings()).restore(ByteArrayInputStream(file), pass)
        assertEquals(listOf(1L, 2L, 3L), dao.all().map { it.timestampMs })
    }

    @Test
    fun backupWithoutAConnectionLeavesTheWorkingOneAlone() = runBlocking {
        val file = backupOf(FakeDao(listOf(reading(1))), FakeSettings())
        val settings = FakeSettings("mongodb://keep:me@h/db", "db")
        val result = AppBackup(FakeDao(), settings).restore(ByteArrayInputStream(file), pass)
        assertEquals(false, result.connectionRestored)
        assertEquals("mongodb://keep:me@h/db", settings.uri); assertEquals("db", settings.database)
    }

    @Test
    fun wrongPassphraseChangesNothing() {
        val file = backupOf(FakeDao(listOf(reading(1))), FakeSettings("mongodb://new@h/db", "newdb"))
        val dao = FakeDao(listOf(reading(9))); val settings = FakeSettings("mongodb://old@h/db", "olddb")
        assertThrows(BackupException::class.java) {
            runBlocking { AppBackup(dao, settings).restore(ByteArrayInputStream(file), "not the passphrase") }
        }
        assertEquals(listOf(9L), runBlocking { dao.all() }.map { it.timestampMs })
        assertEquals("mongodb://old@h/db", settings.uri); assertEquals("olddb", settings.database)
    }
}
