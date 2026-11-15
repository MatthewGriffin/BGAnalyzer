package app.bganalyzer.settings

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** The Nightscout REST settings as the backup sees them. [RestStore] implements this. */
interface RestSettings {
    /** `mongo` (default) or `rest`: which source a sync reads from. */
    var source: String
    var url: String
    /** `none`, `token` or `secret`. */
    var authType: String
    /** The token or API secret. Stored encrypted. */
    var secret: String
}

/**
 * Settings for reading Nightscout over its REST API. Kept apart from [ConnectionStore] on purpose: the saved MongoDB
 * connection is never touched by this. The token or secret is encrypted with its own Keystore key.
 * Do not rename the file, keys or alias without a migration.
 */
class RestStore(context: Context) : RestSettings {
    private val prefs = context.applicationContext.getSharedPreferences("nightscout_rest", Context.MODE_PRIVATE)

    override var source: String
        get() = prefs.getString(KEY_SOURCE, SOURCE_MONGO) ?: SOURCE_MONGO
        set(value) = prefs.edit { putString(KEY_SOURCE, if (value == SOURCE_REST) SOURCE_REST else SOURCE_MONGO) }

    override var url: String
        get() = prefs.getString(KEY_URL, "") ?: ""
        set(value) = prefs.edit { putString(KEY_URL, value.trim()) }

    override var authType: String
        get() = prefs.getString(KEY_AUTH, AUTH_NONE) ?: AUTH_NONE
        set(value) = prefs.edit { putString(KEY_AUTH, if (value == AUTH_TOKEN || value == AUTH_SECRET) value else AUTH_NONE) }

    override var secret: String
        get() {
            val stored = prefs.getString(KEY_SECRET, null) ?: return ""
            return runCatching {
                val bytes = Base64.decode(stored, Base64.NO_WRAP)
                val cipher = Cipher.getInstance(TRANSFORMATION)
                cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, IV_LENGTH))
                String(cipher.doFinal(bytes, IV_LENGTH, bytes.size - IV_LENGTH), Charsets.UTF_8)
            }.getOrDefault("")
        }
        set(value) {
            if (value.isEmpty()) { prefs.edit { remove(KEY_SECRET) }; return }
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val bytes = cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
            prefs.edit { putString(KEY_SECRET, Base64.encodeToString(bytes, Base64.NO_WRAP)) }
        }

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return generator.generateKey()
    }

    companion object {
        const val SOURCE_MONGO = "mongo"
        const val SOURCE_REST = "rest"
        const val AUTH_NONE = "none"
        const val AUTH_TOKEN = "token"
        const val AUTH_SECRET = "secret"
        private const val KEY_ALIAS = "bganalyzer_rest"
        private const val KEY_SOURCE = "source"
        private const val KEY_URL = "url"
        private const val KEY_AUTH = "auth"
        private const val KEY_SECRET = "secret"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val IV_LENGTH = 12
    }
}
