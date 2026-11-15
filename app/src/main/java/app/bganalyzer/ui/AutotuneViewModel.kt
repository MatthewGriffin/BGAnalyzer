package app.bganalyzer.ui

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

    private suspend fun compute(days: Int): AutotuneState =
        when (val r = AutotuneFromDb.run(db, days, _peak.value, System.currentTimeMillis()) { d, n -> _state.value = AutotuneState.Running(d, n) }) {
            is AutotuneFromDb.Outcome.Failed -> AutotuneState.Failed(r.message)
            is AutotuneFromDb.Outcome.Done -> AutotuneState.Done(r.advice, r.result, days)
        }

    companion object {
        const val KEY_PEAK = "insulin_peak"
        const val KEY_DAYS = "autotune_days"
        /** Peak times AAPS uses: rapid-acting 75, ultra-rapid (Fiasp) 55, Lyumjev 45. */
        val DAY_CHOICES = listOf(5, 7, 14, 21, 30)
        val INSULIN_PEAKS = listOf(75, 55, 45)
        private const val HOUR_MS = 3_600_000L
        const val DAY_MS = 24 * HOUR_MS
    }
}
