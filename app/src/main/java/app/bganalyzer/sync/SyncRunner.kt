package app.bganalyzer.sync

import android.content.Context
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.rest.RestAuth
import app.bganalyzer.rest.RestSyncSource
import app.bganalyzer.settings.ConnectionStore
import app.bganalyzer.settings.RestStore
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Runs one sync from whichever source is chosen. Shared by the Sync button and the background sync. Blocks: call off the main thread. */
class SyncRunner(private val context: Context) {
    private val store = ConnectionStore(context)
    private val rest = RestStore(context)
    private val prefs = context.getSharedPreferences("view_settings", Context.MODE_PRIVATE)

    val hasConnection: Boolean
        get() = if (rest.source == RestStore.SOURCE_REST) rest.url.isNotBlank() else store.uri.isNotBlank() && store.database.isNotBlank()

    suspend fun run(days: Int, onProgress: (Int) -> Unit = {}): SyncResult = lock.withLock { runLocked(days, onProgress) }

    private suspend fun runLocked(days: Int, onProgress: (Int) -> Unit): SyncResult {
        val db = AppDatabase.get(context)
        val now = System.currentTimeMillis()
        // Every few days also look for holes anywhere in the period, not only the last week.
        val deep = now - prefs.getLong(KEY_DEEP, 0L) > SyncPlanner.DEEP_CHECK_EVERY_MS
        val result = if (rest.source == RestStore.SOURCE_REST) {
            val auth = when (rest.authType) {
                RestStore.AUTH_TOKEN -> RestAuth.Token(rest.secret)
                RestStore.AUTH_SECRET -> RestAuth.ApiSecret(rest.secret)
                else -> RestAuth.None
            }
            RestSyncSource(rest.url, auth).use { NightscoutSync(db).run(it, days, onProgress, deep) }
        } else NightscoutSync(db).run(store.uri, store.database, days, onProgress, deep)
        if (deep) prefs.edit().putLong(KEY_DEEP, now).apply()
        return result
    }

    private companion object {
        const val KEY_DEEP = "last_deep_gap_check"
        /** The button and the background sync never run at the same time. */
        val lock = Mutex()
    }
}
