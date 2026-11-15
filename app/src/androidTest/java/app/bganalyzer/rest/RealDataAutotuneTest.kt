package app.bganalyzer.rest

import android.util.Log
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.bganalyzer.autotune.AutotuneFromDb
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.sync.NightscoutSync
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeNotNull
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Local only: syncs a month from a real Nightscout site over REST into a throwaway in-memory database and runs autotune
 * on it, logging a summary under the tag REALCHECK. `-Pandroid.testInstrumentationRunnerArguments.restUrl=https://...`
 */
@RunWith(AndroidJUnit4::class)
class RealDataAutotuneTest {
    @Test
    fun autotuneOnRealData(): Unit = runBlocking<Unit> {
        val url = InstrumentationRegistry.getArguments().getString("restUrl")
        assumeNotNull(url)
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(ctx, AppDatabase::class.java).build()
        try {
            val r = RestSyncSource(url!!, RestAuth.None).use { NightscoutSync(db).run(it, 30) }
            Log.i("REALCHECK", "synced glucose=${r.glucoseFetched} treatments=${r.treatmentsFetched} iob=${r.iobFetched} profiles=${r.profilesFetched}")
            val now = System.currentTimeMillis()
            val day = 86_400_000L
            val tbs = db.treatmentDao().validBetween(now - 30 * day, now)
            val segs = app.bganalyzer.domain.BasalTimeline.tempSegments(tbs, now - 30 * day, now)
            for (d in 29 downTo 0) {
                val from = now - (d + 1) * day; val to = now - d * day
                val covered = segs.sumOf { (minOf(it.endMs, to) - maxOf(it.startMs, from)).coerceAtLeast(0) }
                val n = tbs.count { it.timestampMs in from until to }
                val g = db.glucoseReadingDao().between(from, to).size
                val bol = tbs.count { it.timestampMs in from until to && (it.insulin ?: 0.0) > 0 }
                val carb = tbs.count { it.timestampMs in from until to && (it.carbs ?: 0.0) > 0 }
                Log.i("REALCHECK", "day-%02d treatments=%d tempBasalCover=%d%% glucose=%d boluses=%d carbEntries=%d".format(d, n, 100 * covered / day, g, bol, carb))
            }
            when (val o = AutotuneFromDb.run(db, 14, 75, now)) {
                is AutotuneFromDb.Outcome.Failed -> Log.i("REALCHECK", "FAILED: ${o.message}")
                is AutotuneFromDb.Outcome.Done -> {
                    val a = o.advice
                    Log.i("REALCHECK", "days tuned ${a.daysTuned}, skipped ${o.result.skipped.joinToString { it.date + ":" + it.reason }}")
                    Log.i("REALCHECK", "ISF mg/dL ${a.currentIsf} -> ${a.tunedIsf}; CR ${a.currentCarbRatio} -> ${a.tunedCarbRatio}")
                    a.hours.forEach { Log.i("REALCHECK", "h%02d %.3f -> tuned %.3f suggested %.3f %s %s".format(it.hour, it.current, it.tuned, it.suggested, it.confidence, it.heldReason ?: "")) }
                    o.result.log.takeLast(6).forEach { Log.i("REALCHECK", "log: $it") }
                }
            }
        } finally {
            db.close()
        }
    }
}
