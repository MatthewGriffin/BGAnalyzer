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

/**
 * Keeps the MongoDB address (which contains the password) and the database name.
 * The address is encrypted with a key held in the Android Keystore, so it cannot be read from a copy of the file.
 */
class ConnectionStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("connection", Context.MODE_PRIVATE)

    var database: String
        get() = prefs.getString(KEY_DATABASE, "") ?: ""
        set(value) = prefs.edit { putString(KEY_DATABASE, value) }

    /** The stored address, or an empty string when none is stored or it can no longer be decrypted. */
    var uri: String
        get() {
            val stored = prefs.getString(KEY_URI, null) ?: return ""
            return runCatching {
                val bytes = Base64.decode(stored, Base64.NO_WRAP)
                val cipher = Cipher.getInstance(TRANSFORMATION)
                cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, IV_LENGTH))
                String(cipher.doFinal(bytes, IV_LENGTH, bytes.size - IV_LENGTH), Charsets.UTF_8)
            }.getOrDefault("")
        }
        set(value) {
            if (value.isEmpty()) {
                prefs.edit { remove(KEY_URI) }
                return
            }
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val bytes = cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
            prefs.edit { putString(KEY_URI, Base64.encodeToString(bytes, Base64.NO_WRAP)) }
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

    private companion object {
        const val KEY_ALIAS = "bganalyzer_connection"
        const val KEY_URI = "uri"
        const val KEY_DATABASE = "database"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_LENGTH = 12
    }
}
