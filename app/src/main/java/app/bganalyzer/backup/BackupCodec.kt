package app.bganalyzer.backup

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.IobSampleEntity
import app.bganalyzer.data.ProfileEntity
import app.bganalyzer.data.TreatmentEntity
import app.bganalyzer.sync.GlucoseEntryMapper
import org.bson.Document
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.security.GeneralSecurityException
import java.security.SecureRandom
import java.util.Base64
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/** Everything the app saves. Add new kinds of data as new optional fields, never by changing existing ones. */
data class BackupData(
    val createdMs: Long,
    /** The MongoDB address, which includes the password. Null when none was saved. */
    val connectionUri: String?,
    val connectionDatabase: String?,
    val glucose: List<GlucoseReadingEntity>,
    /** Added after version 1 files existed; an older file simply has none. */
    val treatments: List<TreatmentEntity> = emptyList(),
    val profiles: List<ProfileEntity> = emptyList(),
    /** Insulin on board reported by the loop. Sync coverage is not saved: it is rebuilt by the next sync. */
    val iob: List<IobSampleEntity> = emptyList(),
)

class BackupException(val reason: Reason, message: String) : Exception(message) {
    enum class Reason { NOT_A_BACKUP, WRONG_PASSPHRASE_OR_DAMAGED, NEWER_VERSION, DAMAGED }
}

/**
 * The backup file format. The file is a small JSON envelope holding the data, which is gzip-compressed and
 * encrypted with AES-256-GCM under a key derived from the user's passphrase (PBKDF2-HMAC-SHA256).
 *
 * Compatibility rules, pinned by `BackupCodecTest` and the committed fixture in `src/test/resources/backup`:
 * - Every later version of the app must still read version 1 files.
 * - New data is added as new optional fields; readers ignore fields they do not know.
 * - A file with a higher version than the app understands is refused with a clear message, never half-read.
 */
object BackupCodec {
    const val VERSION = 1
    const val MIN_PASSPHRASE_LENGTH = 8
    private const val ENVELOPE_FORMAT = "bganalyzer-encrypted-backup"
    private const val PAYLOAD_FORMAT = "bganalyzer-backup"
    private const val KDF = "PBKDF2WithHmacSHA256"
    private const val ITERATIONS = 600_000
    private const val AAD = "bganalyzer-backup-v1"

    fun encode(data: BackupData, passphrase: String): ByteArray {
        require(passphrase.length >= MIN_PASSPHRASE_LENGTH) { "passphrase too short" }
        val payload = Document("format", PAYLOAD_FORMAT).append("version", VERSION).append("createdMs", data.createdMs)
            .append(
                "connection",
                Document("uri", data.connectionUri).append("database", data.connectionDatabase),
            )
            .append("glucose", data.glucose.map { listOf(it.timestampMs, it.mgdl) })
            .append("treatments", data.treatments.map(::treatmentDoc))
            .append("profiles", data.profiles.map(::profileDoc))
            .append("iob", data.iob.map(::iobDoc))
        val salt = ByteArray(16).also(SecureRandom()::nextBytes)
        val iv = ByteArray(12).also(SecureRandom()::nextBytes)
        val sealed = cipher(Cipher.ENCRYPT_MODE, key(passphrase, salt, ITERATIONS), iv)
            .doFinal(gzip(payload.toJson().toByteArray(Charsets.UTF_8)))
        val b64 = Base64.getEncoder()
        return Document("format", ENVELOPE_FORMAT).append("version", VERSION).append("kdf", KDF)
            .append("iterations", ITERATIONS).append("salt", b64.encodeToString(salt))
            .append("iv", b64.encodeToString(iv)).append("data", b64.encodeToString(sealed))
            .toJson().toByteArray(Charsets.UTF_8)
    }

    /** Reads a backup fully, or throws [BackupException]. Nothing is applied by this function. */
    fun decode(bytes: ByteArray, passphrase: String): BackupData {
        val envelope = try {
            Document.parse(String(bytes, Charsets.UTF_8))
        } catch (e: Exception) {
            throw BackupException(BackupException.Reason.NOT_A_BACKUP, "This file is not a BGAnalyzer backup.")
        }
        if (envelope["format"] != ENVELOPE_FORMAT) {
            throw BackupException(BackupException.Reason.NOT_A_BACKUP, "This file is not a BGAnalyzer backup.")
        }
        val version = (envelope["version"] as? Number)?.toInt() ?: throw damaged()
        if (version > VERSION) throw newer(version)
        val plain = try {
            val b64 = Base64.getDecoder()
            val iterations = (envelope["iterations"] as? Number)?.toInt() ?: throw damaged()
            if (iterations !in 1_000..10_000_000) throw damaged()
            val salt = b64.decode(envelope["salt"] as? String ?: throw damaged())
            val iv = b64.decode(envelope["iv"] as? String ?: throw damaged())
            val sealed = b64.decode(envelope["data"] as? String ?: throw damaged())
            gunzip(cipher(Cipher.DECRYPT_MODE, key(passphrase, salt, iterations), iv).doFinal(sealed))
        } catch (e: BackupException) {
            throw e
        } catch (e: GeneralSecurityException) {
            throw BackupException(
                BackupException.Reason.WRONG_PASSPHRASE_OR_DAMAGED,
                "Wrong passphrase, or the backup file is damaged.",
            )
        } catch (e: Exception) {
            throw damaged()
        }
        return parsePayload(plain)
    }

    private fun parsePayload(plain: ByteArray): BackupData {
        val payload = try {
            Document.parse(String(plain, Charsets.UTF_8))
        } catch (e: Exception) {
            throw damaged()
        }
        if (payload["format"] != PAYLOAD_FORMAT) throw damaged()
        val version = (payload["version"] as? Number)?.toInt() ?: throw damaged()
        if (version > VERSION) throw newer(version)
        val connection = payload["connection"] as? Document
        val readings = (payload["glucose"] as? List<*> ?: emptyList<Any>()).mapNotNull { row ->
            val pair = row as? List<*> ?: return@mapNotNull null
            val t = (pair.getOrNull(0) as? Number)?.toLong() ?: return@mapNotNull null
            val v = (pair.getOrNull(1) as? Number)?.toDouble() ?: return@mapNotNull null
            if (t <= 0 || v < GlucoseEntryMapper.MIN_MGDL || v > GlucoseEntryMapper.MAX_MGDL) null
            else GlucoseReadingEntity(t, v)
        }
        return BackupData(
            treatments = (payload["treatments"] as? List<*>).orEmpty().mapNotNull { (it as? Document)?.let(::treatmentFrom) },
            profiles = (payload["profiles"] as? List<*>).orEmpty().mapNotNull { (it as? Document)?.let(::profileFrom) },
            iob = (payload["iob"] as? List<*>).orEmpty().mapNotNull { (it as? Document)?.let(::iobFrom) },
            createdMs = (payload["createdMs"] as? Number)?.toLong() ?: 0L,
            connectionUri = (connection?.get("uri") as? String)?.takeIf { it.isNotBlank() },
            connectionDatabase = (connection?.get("database") as? String)?.takeIf { it.isNotBlank() },
            glucose = readings,
        )
    }

    private fun treatmentDoc(t: TreatmentEntity) = Document("id", t.id).append("t", t.timestampMs)
        .append("type", t.eventType).append("insulin", t.insulin).append("carbs", t.carbs).append("smb", t.isSmb)
        .append("rate", t.rateUph).append("dur", t.durationMs).append("pct", t.percentage)
        .append("valid", t.valid).append("srv", t.srvModifiedMs).append("raw", t.rawJson)

    private fun treatmentFrom(d: Document): TreatmentEntity? {
        return TreatmentEntity(
        id = d.getString("id") ?: return null,
        timestampMs = (d["t"] as? Number)?.toLong() ?: return null,
        eventType = d["type"] as? String,
        insulin = (d["insulin"] as? Number)?.toDouble(),
        carbs = (d["carbs"] as? Number)?.toDouble(),
        isSmb = d["smb"] == true,
        rateUph = (d["rate"] as? Number)?.toDouble(),
        durationMs = (d["dur"] as? Number)?.toLong(),
        percentage = (d["pct"] as? Number)?.toDouble(),
        valid = d["valid"] != false,
        srvModifiedMs = (d["srv"] as? Number)?.toLong(),
        rawJson = d["raw"] as? String ?: "{}",
        )
    }

    private fun iobDoc(i: IobSampleEntity) = Document("id", i.id).append("t", i.timestampMs)
        .append("iob", i.iob).append("basal", i.basalIob).append("act", i.activity).append("cob", i.cob)

    private fun iobFrom(d: Document): IobSampleEntity? {
        return IobSampleEntity(
            id = d.getString("id") ?: return null,
            timestampMs = (d["t"] as? Number)?.toLong() ?: return null,
            iob = (d["iob"] as? Number)?.toDouble(),
            basalIob = (d["basal"] as? Number)?.toDouble(),
            activity = (d["act"] as? Number)?.toDouble(),
            cob = (d["cob"] as? Number)?.toDouble(),
        )
    }

    private fun profileDoc(p: ProfileEntity) = Document("id", p.id).append("start", p.startMs)
        .append("default", p.defaultProfile).append("units", p.units).append("tz", p.timezone).append("raw", p.rawJson)

    private fun profileFrom(d: Document): ProfileEntity? {
        return ProfileEntity(
        id = d.getString("id") ?: return null,
        startMs = (d["start"] as? Number)?.toLong() ?: return null,
        defaultProfile = d["default"] as? String,
        units = d["units"] as? String,
        timezone = d["tz"] as? String,
        rawJson = d["raw"] as? String ?: "{}",
        )
    }

    private fun damaged() = BackupException(BackupException.Reason.DAMAGED, "The backup file is damaged.")

    private fun newer(version: Int) = BackupException(
        BackupException.Reason.NEWER_VERSION,
        "This backup was made by a newer version of the app (format $version). Update the app to restore it.",
    )

    private fun key(passphrase: String, salt: ByteArray, iterations: Int): SecretKeySpec {
        val spec = PBEKeySpec(passphrase.toCharArray(), salt, iterations, 256)
        return SecretKeySpec(SecretKeyFactory.getInstance(KDF).generateSecret(spec).encoded, "AES")
    }

    private fun cipher(mode: Int, key: SecretKeySpec, iv: ByteArray): Cipher =
        Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(mode, key, GCMParameterSpec(128, iv))
            updateAAD(AAD.toByteArray(Charsets.UTF_8))
        }

    private fun gzip(bytes: ByteArray): ByteArray = ByteArrayOutputStream().also { out ->
        GZIPOutputStream(out).use { it.write(bytes) }
    }.toByteArray()

    private fun gunzip(bytes: ByteArray): ByteArray = GZIPInputStream(ByteArrayInputStream(bytes)).use { it.readBytes() }
}
