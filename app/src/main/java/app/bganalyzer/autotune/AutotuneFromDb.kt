package app.bganalyzer.autotune

import app.bganalyzer.data.AppDatabase
import app.bganalyzer.domain.BasalTimeline
import app.bganalyzer.domain.ExcludedDays
import app.bganalyzer.domain.ProfileChanges
import app.bganalyzer.domain.ProfileResolver
import app.bganalyzer.domain.ProfileTimeline
import java.time.ZoneId

/** Reads the saved data and runs autotune over it: the part of an autotune run that is not screen code. */
object AutotuneFromDb {
    sealed interface Outcome {
        data class Done(val advice: AutotuneAdvice, val result: AutotuneResult, val profileChangeMs: Long? = null) : Outcome
        data class Failed(val message: String) : Outcome
    }

    private const val HOUR_MS = 3_600_000L
    private const val DAY_MS = 24 * HOUR_MS

    suspend fun run(db: AppDatabase, days: Int, peakMinutes: Int, now: Long, progress: (Int, Int) -> Unit = { _, _ -> }): Outcome {
        val zone = db.profileDao().latest()?.timezone?.let { runCatching { ZoneId.of(it) }.getOrNull() } ?: ZoneId.systemDefault()
        val end = AutotuneRun.defaultEnd(now, zone)
        val from = end - days * DAY_MS
        val lookback = 16L * HOUR_MS
        val entries = ProfileTimeline.entries(db.treatmentDao().profileEvents())
        val resolver = ProfileResolver(entries, db.profileDao().all())
        // Start from the profile in force now (what would be edited): the latest steady one, ignoring a running temporary switch.
        val inForce = ProfileChanges.baseline(entries, now) ?: resolver.at(now) ?: return Outcome.Failed("The profile has no basal rates.")
        val settings = inForce.settings.takeIf { it.isf.isNotEmpty() || it.carbRatio.isNotEmpty() } ?: resolver.settingsAt(now)
        val isf = settings.averageIsfMgdl() ?: return Outcome.Failed("The profile has no insulin sensitivity (ISF).")
        val ic = settings.averageCarbRatio() ?: return Outcome.Failed("The profile has no carb ratio.")
        val today = java.time.LocalDate.ofInstant(java.time.Instant.ofEpochMilli(now), zone).atStartOfDay(zone)
        val basal = (0..23).map { h ->
            ProfileTimeline.rateAt(inForce.basal, today.plusHours(h.toLong()).toInstant().toEpochMilli(), zone) ?: return Outcome.Failed("The profile has no basal rates.")
        }
        // Days run on an older profile say nothing about the current one, and re-tuning them would only push the values further.
        val change = ProfileChanges.lastRealChange(entries, now)
        val changeText = change?.let { java.time.format.DateTimeFormatter.ofPattern("d MMM HH:mm", java.util.Locale.ENGLISH).format(java.time.Instant.ofEpochMilli(it.startMs).atZone(zone)) }
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
        val result = AutotuneRun.run(data, baseline, AutotuneLimits(), zone, end, days, skipDate = { it in excluded }, notBeforeMs = change?.startMs, notBeforeReason = "before your profile change on $changeText", progress = progress)
        if (result.daysTuned == 0) {
            if (change != null && result.skipped.any { it.reason.startsWith("before your profile change") }) {
                // the first whole 4 AM to 4 AM day after the change, and when it ends
                var first = java.time.ZonedDateTime.ofInstant(java.time.Instant.ofEpochMilli(change.startMs), zone).toLocalDate().atTime(AutotuneRun.START_HOUR, 0).atZone(zone)
                if (first.toInstant().toEpochMilli() < change.startMs) first = first.plusDays(1)
                val ready = java.time.format.DateTimeFormatter.ofPattern("d MMM HH:mm", java.util.Locale.ENGLISH).format(first.plusDays(1))
                return Outcome.Failed("Your profile changed on $changeText. Autotune only uses whole days (4 AM to 4 AM) run on the current profile, so the first usable day ends on $ready. Nothing to tune before then.")
            }
            return Outcome.Failed("No day had enough data. Skipped: " + SkippedSummary.text(result.skipped))
        }
        // the low-glucose guard looks only at the days that were used, not at skipped (no insulin, excluded) days
        val skippedDates = result.skipped.map { it.date }.toSet()
        val usedReadings = readings.filter { java.time.LocalDate.ofInstant(java.time.Instant.ofEpochMilli(it.timeMs - AutotuneRun.START_HOUR * HOUR_MS), zone).toString() !in skippedDates }
        return Outcome.Done(AutotuneAdvisor.advise(result, usedReadings, zone), result, change?.startMs)
    }
}
