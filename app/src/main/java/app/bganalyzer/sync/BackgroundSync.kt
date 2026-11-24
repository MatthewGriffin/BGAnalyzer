package app.bganalyzer.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/** Keeps the saved data up to date in the background, so the tabs open with fresh numbers. Read-only against Nightscout. */
class BackgroundSyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val runner = SyncRunner(applicationContext)
        if (!runner.hasConnection) return Result.success()
        // A failed run is simply tried again at the next interval.
        runCatching { runner.run(BackgroundSync.DAYS) }
        runCatching { StaleAlert.checkAndNotify(applicationContext) }
        return Result.success()
    }
}

object BackgroundSync {
    const val DAYS = 14
    private const val WORK = "background_sync"
    private const val PREFS = "view_settings"
    private const val KEY = "background_sync"

    fun enabled(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY, true)

    fun setEnabled(context: Context, on: Boolean) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY, on).apply()
        schedule(context)
    }

    /** Queues the periodic sync (every 3 hours, on any network) or cancels it, following the setting. Safe to call on every start. */
    fun schedule(context: Context) {
        val work = WorkManager.getInstance(context)
        if (!enabled(context)) { work.cancelUniqueWork(WORK); return }
        val request = PeriodicWorkRequestBuilder<BackgroundSyncWorker>(3, TimeUnit.HOURS)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        work.enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.KEEP, request)
    }
}
