package app.bganalyzer.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.bganalyzer.R
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.IobSampleEntity
import app.bganalyzer.sync.DataChecks
import app.bganalyzer.sync.EmptyRange
import app.bganalyzer.sync.Sources
import app.bganalyzer.sync.Span
import app.bganalyzer.sync.SyncPlanner
import app.bganalyzer.domain.BasalSegment
import app.bganalyzer.domain.BasalTimeline
import app.bganalyzer.domain.EffectiveProfile
import app.bganalyzer.domain.ProfileResolver
import app.bganalyzer.domain.ProfileTimeline
import app.bganalyzer.data.TreatmentEntity
import app.bganalyzer.domain.PostMeal
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.TimeInRange
import app.bganalyzer.mongo.ConnectionErrors
import app.bganalyzer.settings.ConnectionStore
import app.bganalyzer.sync.NightscoutSync
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** How insulin is shown with glucose: on the same chart (like AAPS), or in its own panel underneath. */
enum class ChartLayout { OVERLAID, SEPARATE }

sealed interface SyncState {
    data object Idle : SyncState
    data class Running(val stored: Int) : SyncState
    data class Done(val glucose: Int, val treatments: Int, val profiles: Int, val iob: Int, val spans: Int) : SyncState
    data class Failed(val message: String) : SyncState
}

data class GlucoseUiState(
    val days: Int = 7,
    val points: List<GlucoseReadingEntity> = emptyList(),
    val timeInRange: TimeInRange = TimeInRange.EMPTY,
    val fromMs: Long = 0,
    val toMs: Long = 0,
    val unit: GlucoseUnit = GlucoseUnit.MMOL,
    /** Valid treatments in the period, oldest first. */
    val treatments: List<TreatmentEntity> = emptyList(),
    val mealCount: Int = 0,
    val carbsTotal: Double = 0.0,
    /** All insulin from bolus records in the period, including automatic micro-boluses. Basal is not included. */
    val bolusInsulinTotal: Double = 0.0,
    /** Basal over the period: temp basals, with the profile schedule where none was running. */
    val basal: List<BasalSegment> = emptyList(),
    val layout: ChartLayout = ChartLayout.OVERLAID,
    /** Insulin and carbs on board reported by the loop in the period, oldest first. */
    val iob: List<IobSampleEntity> = emptyList(),
    /** How much of the period has never been asked for from Nightscout (not counting the recent tail). Zero when complete. */
    val unsyncedMs: Long = 0,
    /** Days Nightscout returned (almost) nothing for, although the app asked. */
    val emptyDays: List<EmptyRange> = emptyList(),
    /** Every profile change known (switches with their modifier), oldest first; the chart marks those inside the period. */
    val profiles: List<EffectiveProfile> = emptyList(),
)

@OptIn(ExperimentalCoroutinesApi::class)
class GlucoseViewModel(app: Application) : AndroidViewModel(app) {
    private val db = AppDatabase.get(app)
    private val dao = db.glucoseReadingDao()
    private val store = ConnectionStore(app)
    private val days = MutableStateFlow(7)
    private val unit = MutableStateFlow(GlucoseUnit.MMOL)
    private val viewPrefs = app.getSharedPreferences("view_settings", android.content.Context.MODE_PRIVATE)
    private val layout = MutableStateFlow(
        runCatching { ChartLayout.valueOf(viewPrefs.getString("chart_layout", null) ?: "") }.getOrDefault(ChartLayout.OVERLAID),
    )
    /** Bumped to recompute the time window, which moves with the clock. */
    private val refresh = MutableStateFlow(0)

    private val _sync = MutableStateFlow<SyncState>(SyncState.Idle)
    val sync: StateFlow<SyncState> = _sync

    val state: StateFlow<GlucoseUiState> = combine(days, unit, refresh) { d, u, _ -> d to u }
        .flatMapLatest { (d, u) ->
            val to = System.currentTimeMillis()
            val from = to - d * DAY_MS
            // A temp basal that started before the window can still be running at its start, so look back 12 hours.
            combine(
                dao.observeSince(from), db.treatmentDao().observeValidSince(from - BASAL_LOOKBACK_MS),
                db.iobDao().observeSince(from), db.coverageDao().observeAll(), db.treatmentDao().observeProfileEvents(),
            ) { rows, all, iob, coverage, profileEvents ->
                val treatments = all.filter { it.timestampMs >= from }
                val meals = PostMeal.meals(treatments)
                val profiles = db.profileDao().all()
                val entries = ProfileTimeline.entries(profileEvents)
                val zone = profiles.lastOrNull()?.timezone?.let { runCatching { java.time.ZoneId.of(it) }.getOrNull() }
                    ?: java.time.ZoneId.systemDefault()
                GlucoseUiState(
                    d, rows, TimeInRange.of(rows.map { it.mgdl }), from, to, u, treatments,
                    mealCount = meals.size,
                    carbsTotal = meals.sumOf { it.carbs },
                    bolusInsulinTotal = treatments.sumOf { (it.insulin ?: 0.0).coerceAtLeast(0.0) },
                    basal = BasalTimeline.build(all, ProfileResolver(entries, profiles), from, to, zone),
                    profiles = entries,
                    iob = iob,
                    unsyncedMs = SyncPlanner.unsyncedMs(coverage.map { it.source to Span(it.startMs, it.endMs) }, Span(from, to)),
                    emptyDays = run {
                        val period = Span(from, to)
                        fun covered(source: String) = coverage.filter { it.source == source }.map { Span(it.startMs, it.endMs) }
                        DataChecks.emptyRanges(Sources.GLUCOSE, rows.map { it.timestampMs }, covered(Sources.GLUCOSE), period, zone, 100, to) +
                            DataChecks.emptyRanges(Sources.TREATMENTS, all.map { it.timestampMs }, covered(Sources.TREATMENTS), period, zone, 5, to) +
                            DataChecks.emptyRanges(Sources.IOB, iob.map { it.timestampMs }, covered(Sources.IOB), period, zone, 5, to)
                    },
                )
            }
        }
        .combine(layout) { state, l -> state.copy(layout = l) }
        .flowOn(Dispatchers.Default)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), GlucoseUiState())

    val hasConnection: Boolean get() = store.uri.isNotBlank() && store.database.isNotBlank()

    fun setDays(value: Int) = days.update { value }

    /** Moves the window to the current time, e.g. when the screen is opened again. */
    fun refreshWindow() = refresh.update { it + 1 }
    fun setUnit(value: GlucoseUnit) = unit.update { value }

    /** Remembered between launches. */
    fun setLayout(value: ChartLayout) {
        layout.value = value
        viewPrefs.edit().putString("chart_layout", value.name).apply()
    }

    /** Makes the last [days] days complete: only missing or recent stretches are requested. The Overview passes its own period, the Patterns tab its own. */
    fun sync(days: Int) {
        if (_sync.value is SyncState.Running) return
        val uri = store.uri
        val database = store.database
        if (uri.isBlank() || database.isBlank()) {
            _sync.value = SyncState.Failed(getApplication<Application>().getString(R.string.sync_no_connection))
            return
        }
        _sync.value = SyncState.Running(0)
        viewModelScope.launch(Dispatchers.IO) {
            _sync.value = try {
                val result = NightscoutSync(db).run(uri, database, days) { _sync.value = SyncState.Running(it) }
                // The window moves with the clock, so refresh it after new data arrives.
                refresh.update { it + 1 }
                SyncState.Done(result.glucoseFetched, result.treatmentsFetched, result.profilesFetched, result.iobFetched, result.spans)
            } catch (e: Exception) {
                SyncState.Failed(ConnectionErrors.describe(e))
            }
        }
    }

    private companion object {
        const val DAY_MS = 24L * 60 * 60 * 1000
        const val BASAL_LOOKBACK_MS = 12L * 60 * 60 * 1000
    }
}
