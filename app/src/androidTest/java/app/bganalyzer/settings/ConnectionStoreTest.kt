package app.bganalyzer.settings

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Pins how the saved connection is stored, so an update cannot silently lose the user's address.
 * If this fails because a name changed, add a migration instead of editing the test.
 */
@RunWith(AndroidJUnit4::class)
class ConnectionStoreTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun savedValuesSurviveANewStoreInstance() {
        val uri = "mongodb+srv://reader:p%40ss@cluster0.example.net/nightscout"
        ConnectionStore(context).apply { this.uri = uri; database = "nightscout" }
        val reopened = ConnectionStore(context)
        assertEquals(uri, reopened.uri)
        assertEquals("nightscout", reopened.database)
    }

    @Test
    fun storageNamesAreUnchanged() {
        ConnectionStore(context).apply { uri = "mongodb://h/db"; database = "db" }
        val prefs = context.getSharedPreferences("connection", Context.MODE_PRIVATE)
        assertEquals("db", prefs.getString("database", null))
        val stored = prefs.getString("uri", null)
        assertFalse("address must be stored encrypted", stored.isNullOrEmpty() || stored.contains("mongodb"))
    }
}
