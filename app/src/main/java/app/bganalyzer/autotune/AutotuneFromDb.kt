package app.bganalyzer.autotune

import app.bganalyzer.data.AppDatabase
import app.bganalyzer.domain.BasalTimeline
import app.bganalyzer.domain.ExcludedDays
import app.bganalyzer.domain.ProfileResolver
import app.bganalyzer.domain.ProfileTimeline
import java.time.ZoneId

/** Reads the saved data and runs autotune over it: the part of an autotune run that is not screen code. */
object AutotuneFromDb {
    sealed interface Outcome {
        data class Done(val advice: AutotuneAdvice, val result: AutotuneResult) : Outcome
        data class Failed(val message: String) : Outcome
    }

    private const val HOUR_MS = 3_600_000L
    private const val DAY_MS = 24 * HOUR_MS

    suspend fun run(db: AppDatabase, days: Int, peakMinutes: Int, now: Long, progress: (Int, Int) -> Unit = { _, _ -> }): Outcome {
        val zone = db.profileDao().latest()?.timezone?.let { runCatching { ZoneId.of(it) }.getOrNull() } ?: ZoneId.systemDefault()
        val end = AutotuneRun.defaultEnd(now, zone)
        val from = end - days * DAY_MS
        val lookback = 16L * HOUR_MS
        val resolver = ProfileResolver(ProfileTimeline.entries(db.treatmentDao().profileEvents()), db.profileDao().all())
        // start from the profile in force now (what would be edited), not the one at the end of the replayed days
        val settings = resolver.settingsAt(now)
        val isf = settings.averageIsfMgdl() ?: return Outcome.Failed("The profile has no insulin sensitivity (ISF).")
        val ic = settings.averageCarbRatio() ?: return Outcome.Failed("The profile has no carb ratio.")
        val inForce = resolver.at(now) ?: return Outcome.Failed("The profile has no basal rates.")
        val today = java.time.LocalDate.ofInstant(java.time.Instant.ofEpochMilli(now), zone).atStartOfDay(zone)
        val basal = (0..23).map { h ->
            ProfileTimeline.rateAt(inForce.basal, today.plusHours(h.toLong()).toInstant().toEpochMilli(), zone) ?: return Outcome.Failed("The profile has no basal rates.")
        }
        val excluded = db.excludedDayDao().all().map { it.date }.toSet()
        val treatments = ExcludedDays.treatments(db.treatmentDao().validBetween(from - lookback, end), zone, excluded)
        val readings = ExcludedDays.readings(db.glucoseReadingDao().between(from, end), zone, excluded).map { AtReading(it.timestampMs, it.mgdl) }
        // priming and zero-insulin records carry no insulin that acts
        val boluses = treatments.filter { (it.insulin ?: 0.0) > 0 && it.eventType?.contains("prim", ignoreCase = true) != true }.map { Dose(it.timestampMs, it.insulin!!) } +
            // extended boluses (not the ones AAPS emulates with a temp basal, which are already in the temp basals)
            treatments.filter { it.eventType == "Combo Bolus" && (it.durationMs ?: 0L) > 0 }.flatMap { t ->
                val doc = runCatching { org.bson.Document.parse(t.rawJson) }.getOrNull()
                val units = (doc?.get("enteredinsulin") as? Number)?.toDouble() ?: 0.0
                if (doc?.get("isEmulatingTempBasal") == true) emptyList() else AutotuneDoses.extended(t.timestampMs, t.durationMs!!, units)
            }
        val meals = treatments.filter { (it.carbs ?: 0.0) > 0 }.map { AtMeal(it.timestampMs, it.carbs!!) }
        val baseline = AtProfile(basal, isf, ic, (settings.diaHours ?: LocalInsulin.DEFAULT_DIA).coerceAtLeast(LocalInsulin.MIN_DIA), peakMinutes)
        val data = AutotuneData(readings, boluses, meals) { f, t -> BasalTimeline.build(treatments, resolver, f, t, zone) }
        val result = AutotuneRun.run(data, baseline, AutotuneLimits(), zone, end, days, skipDate = { it in excluded }, progress = progress)
        if (result.daysTuned == 0) {
            return Outcome.Failed("No day had enough data. Skipped: " + SkippedSummary.text(result.skipped))
        }
        // the low-glucose guard looks only at the days that were used, not at skipped (no insulin, excluded) days
        val skippedDates = result.skipped.map { it.date }.toSet()
        val usedReadings = readings.filter { java.time.LocalDate.ofInstant(java.time.Instant.ofEpochMilli(it.timeMs - AutotuneRun.START_HOUR * HOUR_MS), zone).toString() !in skippedDates }
        return Outcome.Done(AutotuneAdvisor.advise(result, usedReadings, zone), result)
    }
}
