package app.bganalyzer.backup

import app.bganalyzer.data.GlucoseReadingDao
import app.bganalyzer.data.IobDao
import app.bganalyzer.data.ProfileDao
import app.bganalyzer.data.TreatmentDao
import java.io.InputStream
import java.io.OutputStream

/** The saved connection, as the backup sees it. [app.bganalyzer.settings.ConnectionStore] implements this. */
interface ConnectionSettings {
    var uri: String
    var database: String
}

data class RestoreResult(val readings: Int, val connectionRestored: Boolean, val treatments: Int = 0, val profiles: Int = 0, val iob: Int = 0)

/** Writes and restores the full-app backup. Takes streams so it can be tested without a device. */
class AppBackup(
    private val dao: GlucoseReadingDao,
    private val treatmentDao: TreatmentDao,
    private val profileDao: ProfileDao,
    private val iobDao: IobDao,
    private val settings: ConnectionSettings,
    private val nowMs: () -> Long = System::currentTimeMillis,
    private val excludedDayDao: app.bganalyzer.data.ExcludedDayDao? = null,
    private val restSettings: app.bganalyzer.settings.RestSettings? = null,
) {
    suspend fun export(out: OutputStream, passphrase: String): Int {
        val readings = dao.all()
        val data = BackupData(nowMs(), settings.uri.ifBlank { null }, settings.database.ifBlank { null }, readings, treatmentDao.all(), profileDao.all(), iobDao.all(), excludedDayDao?.all().orEmpty(),
            restSettings?.takeIf { it.url.isNotBlank() }?.let { RestBackup(it.source, it.url, it.authType, it.secret) })
        out.write(BackupCodec.encode(data, passphrase))
        out.flush()
        return readings.size
    }

    /**
     * Restores a backup. The file is read and checked completely first, so a wrong passphrase or damaged
     * file changes nothing. Readings are merged into the existing ones, never deleted. The saved connection
     * is replaced only when the backup contains one, so restoring cannot blank out a working connection.
     */
    suspend fun restore(input: InputStream, passphrase: String): RestoreResult {
        val data = BackupCodec.decode(input.readBytes(), passphrase)
        data.glucose.chunked(1000).forEach { dao.upsertAll(it) }
        data.treatments.chunked(1000).forEach { treatmentDao.upsertAll(it) }
        data.profiles.chunked(1000).forEach { profileDao.upsertAll(it) }
        data.iob.chunked(1000).forEach { iobDao.upsertAll(it) }
        excludedDayDao?.upsertAll(data.excludedDays)
        // Like the MongoDB connection: replaced only when the backup has one, so a restore cannot blank a working setup.
        data.rest?.let { r -> restSettings?.let { it.url = r.url; it.authType = r.authType; it.secret = r.secret; it.source = r.source } }
        val uri = data.connectionUri
        val database = data.connectionDatabase
        val connection = uri != null && database != null
        if (connection) {
            settings.uri = uri!!
            settings.database = database!!
        }
        return RestoreResult(data.glucose.size, connection, data.treatments.size, data.profiles.size, data.iob.size)
    }
}
