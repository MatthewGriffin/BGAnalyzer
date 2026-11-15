package app.bganalyzer.backup

import app.bganalyzer.data.GlucoseReadingEntity
import org.bson.Document
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class BackupCodecTest {
    private val data = BackupData(
        createdMs = 1_790_000_000_000L,
        connectionUri = "mongodb+srv://reader:p%40ss@cluster0.example.net/nightscout",
        connectionDatabase = "nightscout",
        glucose = listOf(GlucoseReadingEntity(1_000L, 5.5 * 18), GlucoseReadingEntity(2_000L, 120.0)),
    )
    private val pass = "correct horse"

    private fun reason(block: () -> Unit) = assertThrows(BackupException::class.java, block).reason

    @Test
    fun roundTripKeepsEverything() {
        assertEquals(data, BackupCodec.decode(BackupCodec.encode(data, pass), pass))
    }

    @Test
    fun fileDoesNotContainTheAddressInThePlain() {
        val text = String(BackupCodec.encode(data, pass), Charsets.UTF_8)
        assertFalse(text.contains("mongodb")); assertFalse(text.contains("p%40ss"))
    }

    @Test
    fun noConnectionIsKeptAsNull() {
        val bare = data.copy(connectionUri = null, connectionDatabase = null)
        val back = BackupCodec.decode(BackupCodec.encode(bare, pass), pass)
        assertNull(back.connectionUri); assertNull(back.connectionDatabase)
    }

    @Test
    fun wrongPassphraseIsRefused() {
        val file = BackupCodec.encode(data, pass)
        assertEquals(BackupException.Reason.WRONG_PASSPHRASE_OR_DAMAGED, reason { BackupCodec.decode(file, "wrong passphrase") })
    }

    @Test
    fun tamperedFileIsRefused() {
        val doc = Document.parse(String(BackupCodec.encode(data, pass)))
        val raw = java.util.Base64.getDecoder().decode(doc.getString("data"))
        raw[raw.size / 2] = (raw[raw.size / 2].toInt() xor 1).toByte()
        doc["data"] = java.util.Base64.getEncoder().encodeToString(raw)
        assertEquals(BackupException.Reason.WRONG_PASSPHRASE_OR_DAMAGED, reason { BackupCodec.decode(doc.toJson().toByteArray(), pass) })
    }

    @Test
    fun otherFilesAreNotBackups() {
        assertEquals(BackupException.Reason.NOT_A_BACKUP, reason { BackupCodec.decode("hello".toByteArray(), pass) })
        assertEquals(BackupException.Reason.NOT_A_BACKUP, reason { BackupCodec.decode("""{"a":1}""".toByteArray(), pass) })
    }

    @Test
    fun newerFormatIsRefusedWithAClearReason() {
        val doc = Document.parse(String(BackupCodec.encode(data, pass))).append("version", BackupCodec.VERSION + 1)
        assertEquals(BackupException.Reason.NEWER_VERSION, reason { BackupCodec.decode(doc.toJson().toByteArray(), pass) })
    }

    @Test
    fun shortPassphraseIsRejectedWhenWriting() {
        assertThrows(IllegalArgumentException::class.java) { BackupCodec.encode(data, "short") }
    }

    /**
     * A real version 1 file, committed so every later version of the app is tested against it.
     * If this fails, the reader changed in a way that breaks existing backups: fix the reader, not the file.
     */
    @Test
    fun committedVersion1FileStillReads() {
        val bytes = javaClass.getResourceAsStream("/backup/v1.bgbackup")!!.readBytes()
        val back = BackupCodec.decode(bytes, "fixture-pass-v1")
        assertEquals("mongodb+srv://fixture:secret@cluster0.example.net/nightscout", back.connectionUri)
        assertEquals("nightscout", back.connectionDatabase)
        assertEquals(listOf(GlucoseReadingEntity(1_790_000_000_000L, 117.0), GlucoseReadingEntity(1_790_000_300_000L, 121.0)), back.glucose)
    }
}
