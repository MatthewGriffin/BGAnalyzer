package app.bganalyzer.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.bganalyzer.autotune.AtMeal
import app.bganalyzer.autotune.AtProfile
import app.bganalyzer.autotune.AtReading
import app.bganalyzer.autotune.AutotuneAdvice
import app.bganalyzer.autotune.AutotuneAdvisor
import app.bganalyzer.autotune.AutotuneData
import app.bganalyzer.autotune.AutotuneDoses
import app.bganalyzer.autotune.AutotuneLimits
import app.bganalyzer.autotune.AutotuneResult
import app.bganalyzer.autotune.AutotuneRun
import app.bganalyzer.autotune.Dose
import app.bganalyzer.autotune.LocalInsulin
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.domain.BasalTimeline
import app.bganalyzer.domain.ExcludedDays
import app.bganalyzer.domain.ProfileResolver
import app.bganalyzer.domain.ProfileTimeline
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.time.ZoneId

sealed interface AutotuneState {
    data object Idle : AutotuneState
    data class Running(val day: Int, val of: Int) : AutotuneState
    data class Done(val advice: AutotuneAdvice, val result: AutotuneResult, val days: Int) : AutotuneState
    data class Failed(val message: String) : AutotuneState
}

class AutotuneViewModel(app: Application) : AndroidViewModel(app) {
    private val db = AppDatabase.get(app)
    private val prefs = app.getSharedPreferences("view_settings", android.content.Context.MODE_PRIVATE)
    private val _state = MutableStateFlow<AutotuneState>(AutotuneState.Idle)
    val state: StateFlow<AutotuneState> = _state

    /** The insulin's peak activity time in minutes. The profile does not carry it, so the user picks the insulin type. */
    private val _peak = MutableStateFlow(prefs.getInt(KEY_PEAK, LocalInsulin.DEFAULT_PEAK).takeIf { it in INSULIN_PEAKS } ?: LocalInsulin.DEFAULT_PEAK)
    val peak: StateFlow<Int> = _peak

    fun setPeak(minutes: Int) {
        _peak.value = minutes
        prefs.edit().putInt(KEY_PEAK, minutes).apply()
    }

    /** Runs autotune over the last [days] full days (4 AM to 4 AM). Reads the saved data only; sync first for a full period. */
    fun run(days: Int) {
        if (_state.value is AutotuneState.Running) return
        _state.value = AutotuneState.Running(0, days)
        viewModelScope.launch(Dispatchers.Default) {
            _state.value = try { compute(days) } catch (e: Exception) { AutotuneState.Failed(e.message ?: e.javaClass.simpleName) }
        }
    }

    fun clear() { _state.value = AutotuneState.Idle }

    private suspend fun compute(days: Int): AutotuneState {
        val now = System.currentTimeMillis()
        val zone = db.profileDao().latest()?.timezone?.let { runCatching { ZoneId.of(it) }.getOrNull() } ?: ZoneId.systemDefault()
        val end = AutotuneRun.defaultEnd(now, zone)
        val from = end - days * DAY_MS
        val lookback = 16L * HOUR_MS
        val resolver = ProfileResolver(ProfileTimeline.entries(db.treatmentDao().profileEvents()), db.profileDao().all())
        val settings = resolver.settingsAt(end)
        val isf = settings.averageIsfMgdl() ?: return AutotuneState.Failed("The profile has no insulin sensitivity (ISF).")
        val ic = settings.averageCarbRatio() ?: return AutotuneState.Failed("The profile has no carb ratio.")
        val basal = (0..23).map { h ->
            val t = java.time.LocalDate.ofInstant(java.time.Instant.ofEpochMilli(end), zone).minusDays(1).atStartOfDay(zone).plusHours(h.toLong()).toInstant().toEpochMilli()
            resolver.basalAt(t, zone) ?: return AutotuneState.Failed("The profile has no basal rates.")
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
        val baseline = AtProfile(basal, isf, ic, (settings.diaHours ?: LocalInsulin.DEFAULT_DIA).coerceAtLeast(LocalInsulin.MIN_DIA), _peak.value)
        val data = AutotuneData(readings, boluses, meals) { f, t -> BasalTimeline.build(treatments, resolver, f, t, zone) }
        val result = AutotuneRun.run(data, baseline, AutotuneLimits(), zone, end, days, skipDate = { it in excluded }) { d, n -> _state.value = AutotuneState.Running(d, n) }
        if (result.daysTuned == 0) {
            return AutotuneState.Failed("No day had enough data. Skipped: " + result.skipped.joinToString { "${it.date} (${it.reason})" })
        }
        return AutotuneState.Done(AutotuneAdvisor.advise(result, readings, zone), result, days)
    }

    companion object {
        const val KEY_PEAK = "insulin_peak"
        /** Peak times AAPS uses: rapid-acting 75, ultra-rapid (Fiasp) 55, Lyumjev 45. */
        val INSULIN_PEAKS = listOf(75, 55, 45)
        private const val HOUR_MS = 3_600_000L
        const val DAY_MS = 24 * HOUR_MS
    }
}
