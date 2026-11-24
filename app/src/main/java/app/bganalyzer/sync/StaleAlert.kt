package app.bganalyzer.sync

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import app.bganalyzer.R
import app.bganalyzer.data.AppDatabase

/** An optional notification when no glucose reading has arrived for a while, checked after each background sync. Off by default. */
object StaleAlert {
    const val STALE_AFTER_MS = 2L * 3_600_000L
    /** Not repeated more often than this. */
    private const val REPEAT_MS = 6L * 3_600_000L
    private const val PREFS = "view_settings"
    private const val KEY = "stale_alert"
    private const val KEY_LAST = "stale_alert_last_ms"
    private const val CHANNEL = "data_stopped"

    fun enabled(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY, false)

    fun setEnabled(context: Context, on: Boolean) { context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY, on).apply() }

    /** True when [newestMs] is old enough to raise the alert and the last one was long enough ago. Pure, for tests. */
    fun shouldAlert(newestMs: Long?, nowMs: Long, lastAlertMs: Long): Boolean =
        newestMs != null && nowMs - newestMs >= STALE_AFTER_MS && nowMs - lastAlertMs >= REPEAT_MS

    suspend fun checkAndNotify(context: Context) {
        if (!enabled(context)) return
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        val newest = AppDatabase.get(context).glucoseReadingDao().newestTimestamp()
        if (!shouldAlert(newest, now, prefs.getLong(KEY_LAST, 0L))) return
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, context.getString(R.string.stale_channel), NotificationManager.IMPORTANCE_DEFAULT))
        val hours = (now - newest!!) / 3_600_000L
        manager.notify(1, NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_error)
            .setContentTitle(context.getString(R.string.stale_title))
            .setContentText(context.getString(R.string.stale_text, hours))
            .setAutoCancel(true).build())
        prefs.edit().putLong(KEY_LAST, now).apply()
    }
}
