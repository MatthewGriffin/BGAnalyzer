package app.bganalyzer.backup

import app.bganalyzer.data.GlucoseReadingDao
import java.io.InputStream
import java.io.OutputStream

/** The saved connection, as the backup sees it. [app.bganalyzer.settings.ConnectionStore] implements this. */
interface ConnectionSettings {
    var uri: String
    var database: String
}

data class RestoreResult(val readings: Int, val connectionRestored: Boolean)

/** Writes and restores the full-app backup. Takes streams so it can be tested without a device. */
class AppBackup(
    private val dao: GlucoseReadingDao,
    private val settings: ConnectionSettings,
    private val nowMs: () -> Long = System::currentTimeMillis,
) {
    suspend fun export(out: OutputStream, passphrase: String): Int {
        val readings = dao.all()
        val data = BackupData(nowMs(), settings.uri.ifBlank { null }, settings.database.ifBlank { null }, readings)
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
        val uri = data.connectionUri
        val database = data.connectionDatabase
        val connection = uri != null && database != null
        if (connection) {
            settings.uri = uri!!
            settings.database = database!!
        }
        return RestoreResult(data.glucose.size, connection)
    }
}
