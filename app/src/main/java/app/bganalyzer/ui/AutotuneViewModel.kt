package app.bganalyzer.ui

import app.bganalyzer.data.zone
import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.bganalyzer.autotune.AtMeal
import app.bganalyzer.autotune.AtProfile
import app.bganalyzer.autotune.AtReading
import app.bganalyzer.autotune.AutotuneAdvice
import app.bganalyzer.autotune.AutotuneAdvisor
import app.bganalyzer.autotune.AutotuneFromDb
import app.bganalyzer.autotune.AutotuneDoses
import app.bganalyzer.autotune.AutotuneLimits
import app.bganalyzer.autotune.AutotuneResult
import app.bganalyzer.autotune.AutotuneRun
import app.bganalyzer.autotune.Dose
import app.bganalyzer.autotune.LocalInsulin
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.data.ExcludedDayEntity
import app.bganalyzer.domain.DayQuality
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import app.bganalyzer.domain.BasalTimeline
import app.bganalyzer.domain.ExcludedDays
import app.bganalyzer.domain.ProfileResolver
import app.bganalyzer.domain.ProfileTimeline
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.time.ZoneId

/** The suggestions of an earlier run (24 pump-rounded hourly rates) and when it was made. */
data class PreviousRun(val atMs: Long, val rates: List<Double>)

data class DayQualityState(val excluded: List<ExcludedDayEntity> = emptyList(), val noInsulinDays: List<String> = emptyList())

sealed interface AutotuneState {
    data object Idle : AutotuneState
    data class Running(val day: Int, val of: Int) : AutotuneState
    data class Done(val advice: AutotuneAdvice, val result: AutotuneResult, val days: Int, val profileChangeMs: Long? = null, val usedFirst: java.time.LocalDate? = null, val usedLast: java.time.LocalDate? = null, val previous: PreviousRun? = null) : AutotuneState
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

    /** Days to replay. Kept here so the choice survives tab switches and always matches the result shown. */
    private val _days = MutableStateFlow(prefs.getInt(KEY_DAYS, 14).takeIf { it in DAY_CHOICES } ?: 14)
    val days: StateFlow<Int> = _days

    fun setDays(value: Int) {
        _days.value = value
        prefs.edit().putInt(KEY_DAYS, value).apply()
    }

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

    private val refresh = MutableStateFlow(0)
    /** Recompute the day lists, e.g. when the tab is opened after a sync. */
    fun refresh() = refresh.update { it + 1 }

    /** Days marked as bad data, and days with glucose but no insulin records at all (candidates to exclude), for the days chosen. */
    val dayQuality: StateFlow<DayQualityState> = combine(_days, db.excludedDayDao().observeAll(), refresh) { d, excluded, _ ->
        val to = System.currentTimeMillis()
        val from = to - d * DAY_MS
        val zone = db.profileDao().zone()
        val dates = excluded.map { it.date }.toSet()
        val noInsulin = DayQuality.daysWithoutInsulin(
            db.treatmentDao().validBetween(from - 12 * HOUR_MS, to), db.glucoseReadingDao().between(from, to).map { it.timestampMs }, zone, from, to, to,
        ).filter { it !in dates }
        DayQualityState(excluded, noInsulin)
    }.flowOn(Dispatchers.Default).stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), DayQualityState())

    // A changed set of excluded days makes the shown result out of date, so it is cleared.
    fun excludeDay(date: String, note: String) = excludeDays(listOf(date), note.trim())

    fun excludeDays(dates: List<String>, note: String) {
        val now = System.currentTimeMillis()
        viewModelScope.launch(Dispatchers.IO) { db.excludedDayDao().upsertAll(dates.map { ExcludedDayEntity(it, note, now) }) }
        clearIfDone()
    }

    fun restoreDay(date: String) {
        viewModelScope.launch(Dispatchers.IO) { db.excludedDayDao().delete(date) }
        clearIfDone()
    }

    private fun clearIfDone() { if (_state.value is AutotuneState.Done) _state.value = AutotuneState.Idle }

    private suspend fun compute(days: Int): AutotuneState =
        when (val r = AutotuneFromDb.run(db, days, _peak.value, System.currentTimeMillis()) { d, n -> _state.value = AutotuneState.Running(d, n) }) {
            is AutotuneFromDb.Outcome.Failed -> AutotuneState.Failed(r.message)
            is AutotuneFromDb.Outcome.Done -> AutotuneState.Done(r.advice, r.result, days, r.profileChangeMs, r.usedFirst, r.usedLast, rememberRun(r.advice))
        }

    /**
     * Saves this run's suggestions and returns the run before it, so the screen can show whether the numbers move.
     * Runs less than 6 hours apart count as the same run (the later replaces the earlier).
     */
    private fun rememberRun(advice: AutotuneAdvice): PreviousRun? {
        val now = System.currentTimeMillis()
        fun load(prefix: String): PreviousRun? {
            val at = prefs.getLong(prefix + "_ms", 0L)
            val rates = prefs.getString(prefix + "_rates", null)?.split(',')?.mapNotNull { it.toDoubleOrNull() }
            return if (at > 0 && rates?.size == 24) PreviousRun(at, rates) else null
        }
        fun save(prefix: String, r: PreviousRun?) { prefs.edit().apply { if (r == null) { remove(prefix + "_ms"); remove(prefix + "_rates") } else { putLong(prefix + "_ms", r.atMs); putString(prefix + "_rates", r.rates.joinToString(",")) } }.apply() }
        val rates = advice.hours.sortedBy { it.hour }.map { AutotuneAdvisor.roundToPumpStep(it.suggested) }
        val current = load("run_cur")
        val previous = if (current != null && now - current.atMs > SAME_RUN_MS) current.also { save("run_prev", it) } else load("run_prev")
        save("run_cur", PreviousRun(now, rates))
        return previous
    }

    companion object {
        private const val SAME_RUN_MS = 6L * 3_600_000L
        const val KEY_PEAK = "insulin_peak"
        const val KEY_DAYS = "autotune_days"
        /** Peak times AAPS uses: rapid-acting 75, ultra-rapid (Fiasp) 55, Lyumjev 45. */
        val DAY_CHOICES = listOf(5, 7, 14, 21, 30)
        val INSULIN_PEAKS = listOf(75, 55, 45)
        private const val HOUR_MS = 3_600_000L
        const val DAY_MS = 24 * HOUR_MS
    }
}
