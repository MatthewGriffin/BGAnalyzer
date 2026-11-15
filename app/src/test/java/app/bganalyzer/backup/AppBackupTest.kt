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

    private fun backupOf(
        dao: FakeDao,
        settings: FakeSettings,
        treatments: List<app.bganalyzer.data.TreatmentEntity> = emptyList(),
        profiles: List<app.bganalyzer.data.ProfileEntity> = emptyList(),
        iob: List<app.bganalyzer.data.IobSampleEntity> = emptyList(),
    ): ByteArray = runBlocking {
        ByteArrayOutputStream().also { AppBackup(dao, FakeTreatmentDao(treatments), FakeProfileDao(profiles), FakeIobDao(iob), settings, nowMs = { 5L }).export(it, pass) }.toByteArray()
    }

    @Test
    fun restoreIntoAnEmptyAppBringsEverythingBack() = runBlocking {
        val file = backupOf(FakeDao(listOf(reading(1), reading(2, 150.0))), FakeSettings("mongodb://u:p@h/db", "db"))
        val dao = FakeDao(); val settings = FakeSettings()
        val result = AppBackup(dao, FakeTreatmentDao(), FakeProfileDao(), FakeIobDao(), settings).restore(ByteArrayInputStream(file), pass)
        assertEquals(RestoreResult(2, true), result)
        assertEquals(listOf(reading(1), reading(2, 150.0)), dao.all())
        assertEquals("mongodb://u:p@h/db", settings.uri); assertEquals("db", settings.database)
    }

    @Test
    fun restoreMergesAndNeverDeletesExistingReadings() = runBlocking {
        val file = backupOf(FakeDao(listOf(reading(1), reading(2))), FakeSettings("mongodb://h/db", "db"))
        val dao = FakeDao(listOf(reading(2, 999.0 - 800), reading(3)))
        AppBackup(dao, FakeTreatmentDao(), FakeProfileDao(), FakeIobDao(), FakeSettings()).restore(ByteArrayInputStream(file), pass)
        assertEquals(listOf(1L, 2L, 3L), dao.all().map { it.timestampMs })
    }

    @Test
    fun backupWithoutAConnectionLeavesTheWorkingOneAlone() = runBlocking {
        val file = backupOf(FakeDao(listOf(reading(1))), FakeSettings())
        val settings = FakeSettings("mongodb://keep:me@h/db", "db")
        val result = AppBackup(FakeDao(), FakeTreatmentDao(), FakeProfileDao(), FakeIobDao(), settings).restore(ByteArrayInputStream(file), pass)
        assertEquals(false, result.connectionRestored)
        assertEquals("mongodb://keep:me@h/db", settings.uri); assertEquals("db", settings.database)
    }

    @Test
    fun treatmentsAndProfilesRoundTripAndMergeByKey() = runBlocking {
        val t = app.bganalyzer.data.TreatmentEntity("a1", 10, "Meal Bolus", 2.0, 30.0, false, null, null, null, true, 5L, "{\"x\":1}")
        val p = app.bganalyzer.data.ProfileEntity("p1", 7, "main", "mmol", "Europe/London", "{}")
        val file = backupOf(FakeDao(), FakeSettings(), listOf(t), listOf(p))
        val tDao = FakeTreatmentDao(listOf(t.copy(id = "old", timestampMs = 1))); val pDao = FakeProfileDao()
        val result = AppBackup(FakeDao(), tDao, pDao, FakeIobDao(), FakeSettings()).restore(ByteArrayInputStream(file), pass)
        assertEquals(1, result.treatments); assertEquals(1, result.profiles)
        assertEquals(listOf("old", "a1"), tDao.all().map { it.id })
        assertEquals(t, tDao.rows["a1"]); assertEquals(p, pDao.rows["p1"])
    }

    @Test
    fun insulinOnBoardRoundTrips() = runBlocking {
        val i = app.bganalyzer.data.IobSampleEntity("i1", 42L, 1.25, 0.3, 0.02, 20.0)
        val file = backupOf(FakeDao(), FakeSettings(), iob = listOf(i))
        val iobDao = FakeIobDao()
        val result = AppBackup(FakeDao(), FakeTreatmentDao(), FakeProfileDao(), iobDao, FakeSettings()).restore(ByteArrayInputStream(file), pass)
        assertEquals(1, result.iob); assertEquals(i, iobDao.rows["i1"])
    }

    @Test
    fun wrongPassphraseChangesNothing() {
        val file = backupOf(FakeDao(listOf(reading(1))), FakeSettings("mongodb://new@h/db", "newdb"))
        val dao = FakeDao(listOf(reading(9))); val settings = FakeSettings("mongodb://old@h/db", "olddb")
        assertThrows(BackupException::class.java) {
            runBlocking { AppBackup(dao, FakeTreatmentDao(), FakeProfileDao(), FakeIobDao(), settings).restore(ByteArrayInputStream(file), "not the passphrase") }
        }
        assertEquals(listOf(9L), runBlocking { dao.all() }.map { it.timestampMs })
        assertEquals("mongodb://old@h/db", settings.uri); assertEquals("olddb", settings.database)
    }
}
