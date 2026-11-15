package app.bganalyzer.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.domain.BasalComparison
import app.bganalyzer.domain.BasalComparisonResult
import app.bganalyzer.domain.BlockStats
import app.bganalyzer.domain.EffectiveProfile
import app.bganalyzer.domain.ProfileResolver
import app.bganalyzer.domain.ProfileTimeline
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.MealBlockStats
import app.bganalyzer.domain.PostMeal
import app.bganalyzer.domain.SuggestionResult
import app.bganalyzer.domain.Suggestions
import app.bganalyzer.domain.TimeBlocks
import app.bganalyzer.sync.DataChecks
import app.bganalyzer.sync.EmptyRange
import app.bganalyzer.sync.Sources
import app.bganalyzer.sync.Span
import app.bganalyzer.sync.SyncPlanner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import java.time.ZoneId

data class PatternsState(
    val days: Int = 30,
    val blockHours: Int = 6,
    val loaded: Boolean = false,
    val readingCount: Int = 0,
    val zoneName: String = "",
    val blocks: List<BlockStats> = emptyList(),
    val meals: List<MealBlockStats> = emptyList(),
    val unit: GlucoseUnit = GlucoseUnit.MMOL,
    /** How much of the period has never been requested from Nightscout; see [SyncPlanner.unsyncedMs]. */
    val unsyncedMs: Long = 0,
    /** How the loop's temp basals compared with the profile's scheduled basal; null until loaded. */
    val basal: BasalComparisonResult? = null,
    /** Days Nightscout returned (almost) nothing for, although the app asked. */
    val emptyDays: List<EmptyRange> = emptyList(),
    /** Profile switches in the period, oldest first. */
    val profileChanges: List<EffectiveProfile> = emptyList(),
    val suggestions: SuggestionResult = SuggestionResult(emptyList(), emptyList()),
)

class PatternsViewModel(app: Application) : AndroidViewModel(app) {
    private val db = AppDatabase.get(app)
    private val days = MutableStateFlow(30)
    private val blockHours = MutableStateFlow(6)
    private val refresh = MutableStateFlow(0)

    val state: StateFlow<PatternsState> = combine(days, blockHours, refresh, db.coverageDao().observeAll()) { d, b, _, coverage -> Triple(d, b, coverage) }
        .let { settings ->
            kotlinx.coroutines.flow.flow {
                settings.collect { (d, b, coverage) ->
                    val to = System.currentTimeMillis()
                    val from = to - d * DAY_MS
                    val zone = db.profileDao().latest()?.timezone?.let { runCatching { ZoneId.of(it) }.getOrNull() }
                        ?: ZoneId.systemDefault()
                    val readings = db.glucoseReadingDao().between(from, to)
                    val resolver = ProfileResolver(ProfileTimeline.entries(db.treatmentDao().profileEvents()), db.profileDao().all())
                    val treatments = db.treatmentDao().validBetween(from - 12 * 3_600_000L, to)
                    val blockStats = TimeBlocks.analyze(readings, zone, b)
                    val mealStats = PostMeal.analyze(readings, PostMeal.meals(treatments).filter { it.timeMs >= from }, zone, b)
                    val basalStats = BasalComparison.analyze(treatments, resolver, from, to, zone, b)
                    emit(
                        PatternsState(
                            d, b, true, readings.size, zone.id,
                            blockStats,
                            mealStats,
                            unsyncedMs = SyncPlanner.unsyncedMs(coverage.map { it.source to Span(it.startMs, it.endMs) }, Span(from, to)),
                            basal = basalStats,
                            suggestions = Suggestions.generate(blockStats, mealStats, basalStats),
                            profileChanges = resolver.changes(from, to),
                            emptyDays = run {
                                val period = Span(from, to)
                                fun covered(source: String) = coverage.filter { it.source == source }.map { Span(it.startMs, it.endMs) }
                                DataChecks.emptyRanges(Sources.GLUCOSE, readings.map { it.timestampMs }, covered(Sources.GLUCOSE), period, zone, 100, to) +
                                    DataChecks.emptyRanges(Sources.TREATMENTS, treatments.map { it.timestampMs }, covered(Sources.TREATMENTS), period, zone, 5, to) +
                                    DataChecks.emptyRanges(Sources.IOB, db.iobDao().timestampsSince(from), covered(Sources.IOB), period, zone, 5, to)
                            },
                        ),
                    )
                }
            }
        }
        .flowOn(Dispatchers.Default)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), PatternsState())

    fun setDays(value: Int) = days.update { value }
    fun setBlockHours(value: Int) = blockHours.update { value }
    /** Recompute with the current time and the latest synced data, e.g. when the tab is opened. */
    fun refresh() = refresh.update { it + 1 }

    private companion object {
        const val DAY_MS = 24L * 60 * 60 * 1000
    }
}
