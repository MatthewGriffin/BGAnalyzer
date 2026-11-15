package app.bganalyzer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.bganalyzer.R
import app.bganalyzer.domain.BasalBlockStats
import app.bganalyzer.domain.BasalComparisonResult
import app.bganalyzer.domain.BlockStats
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.MealBlockStats
import app.bganalyzer.domain.PostMeal
import app.bganalyzer.domain.TimeBlocks
import app.bganalyzer.domain.format
import java.util.Locale

private val PERIODS = listOf(7, 14, 30, 60, 90)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PatternsScreen(
    state: PatternsState,
    unit: GlucoseUnit,
    sync: SyncState,
    hasConnection: Boolean,
    onDays: (Int) -> Unit,
    onBlockHours: (Int) -> Unit,
    onSync: () -> Unit,
    onExcludeDay: (String, String) -> Unit = { _, _ -> },
    onRestoreDay: (String) -> Unit = {},
    autotuneState: AutotuneState = AutotuneState.Idle,
    onAutotune: (Int) -> Unit = {},
    onAutotuneClear: () -> Unit = {},
    insulinPeak: Int = 75,
    onInsulinPeak: (Int) -> Unit = {},
) {
    Scaffold(contentWindowInsets = androidx.compose.foundation.layout.WindowInsets(0, 0, 0, 0), topBar = { TopAppBar(title = { Text(stringResource(R.string.patterns_title)) }) }) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(stringResource(R.string.patterns_intro))
            if (state.unsyncedMs > 60 * 60 * 1000L && sync !is SyncState.Running) {
                Text(stringResource(R.string.sync_unsynced_notice), color = MaterialTheme.colorScheme.tertiary)
            }
            androidx.compose.material3.Button(onClick = onSync, enabled = hasConnection && sync !is SyncState.Running) {
                Text(stringResource(R.string.patterns_sync_button, state.days))
            }
            when (sync) {
                is SyncState.Running -> Text(stringResource(R.string.sync_running, sync.stored))
                is SyncState.Done -> Text(stringResource(R.string.sync_done, sync.glucose, sync.treatments, sync.iob, sync.spans), style = MaterialTheme.typography.bodySmall)
                is SyncState.Failed -> Text(sync.message, color = MaterialTheme.colorScheme.error)
                SyncState.Idle -> Unit
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Dropdown(
                    label = stringResource(R.string.range_label),
                    options = PERIODS,
                    selected = state.days,
                    text = { stringResource(R.string.range_days, it) },
                    onSelect = onDays,
                    modifier = Modifier.weight(1f),
                )
                Dropdown(
                    label = stringResource(R.string.patterns_block_label),
                    options = TimeBlocks.ALLOWED_BLOCK_HOURS,
                    selected = state.blockHours,
                    text = { stringResource(R.string.patterns_block_hours, it) },
                    onSelect = onBlockHours,
                    modifier = Modifier.weight(1f),
                )
            }
            EmptyDaysNotice(state.emptyDays)
            ExcludedDaysSection(state, onExcludeDay, onRestoreDay)
            if (state.loaded && state.readingCount == 0) {
                Text(stringResource(R.string.patterns_no_data))
                return@Column
            }
            SuggestionsSection(state, sync is SyncState.Running)
            if (state.zoneName.isNotEmpty()) Text(stringResource(R.string.patterns_timezone, state.zoneName), style = MaterialTheme.typography.bodySmall)
            Text(stringResource(R.string.patterns_glucose_title), style = MaterialTheme.typography.titleMedium)
            state.blocks.forEach { BlockCard(it, unit) }
            ChangesSection(state.changes)
            state.basal?.let { BasalSection(it, state.profileChanges) }
            Text(stringResource(R.string.patterns_meals_title), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(R.string.patterns_meals_intro), style = MaterialTheme.typography.bodySmall)
            state.meals.forEach { MealCard(it, unit) }
            AutotuneSection(autotuneState, unit, insulinPeak, onInsulinPeak, onAutotune, onAutotuneClear)
        }
    }
}

private fun hour(h: Int) = String.format(Locale.US, "%02d:00", h % 24)
private fun pct(v: Double) = String.format(Locale.getDefault(), "%.0f", v)

@Composable
private fun BlockCard(b: BlockStats, unit: GlucoseUnit) {
    val tir = b.timeInRange
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.patterns_block_time, hour(b.startHour), hour(b.endHour)), style = MaterialTheme.typography.titleSmall)
            if (!b.enoughDays) {
                Text(stringResource(R.string.patterns_not_enough, b.days, TimeBlocks.MIN_DAYS))
                return@Column
            }
            Text(stringResource(R.string.patterns_days, b.days), style = MaterialTheme.typography.bodySmall)
            Text(stringResource(R.string.patterns_in_range, pct(tir.inRangePct)))
            Text(stringResource(R.string.patterns_below, pct(tir.lowPct + tir.veryLowPct)))
            Text(stringResource(R.string.patterns_above, pct(tir.highPct + tir.veryHighPct)))
            Text(stringResource(R.string.patterns_average, unit.format(tir.meanMgdl), unit.label))
            if (b.lowDays > 0) Text(stringResource(R.string.patterns_low_days, b.lowDays, b.days), color = MaterialTheme.colorScheme.error)
            if (b.veryLowDays > 0) Text(stringResource(R.string.patterns_very_low_days, b.veryLowDays, b.days), color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun MealCard(m: MealBlockStats, unit: GlucoseUnit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.patterns_block_time, hour(m.startHour), hour(m.endHour)), style = MaterialTheme.typography.titleSmall)
            if (m.meals == 0) {
                Text(stringResource(R.string.patterns_meals_count, 0))
                return@Column
            }
            if (!m.enoughMeals) {
                Text(stringResource(R.string.patterns_meals_not_enough, m.meals, PostMeal.MIN_MEALS))
                return@Column
            }
            Text(stringResource(R.string.patterns_meals_count, m.meals), style = MaterialTheme.typography.bodySmall)
            // A rise is a difference, so it converts without an offset.
            Text(stringResource(R.string.patterns_meal_rise, unit.format(m.medianRiseMgdl), unit.label))
            m.medianAt2hMgdl?.let { Text(stringResource(R.string.patterns_meal_2h, unit.format(it), unit.label)) }
            if (m.withReading2h > 0) Text(stringResource(R.string.patterns_meal_high2h, m.highAt2h, m.withReading2h))
            Text(
                stringResource(R.string.patterns_meal_low4h, m.lowWithin4h, m.meals),
                color = if (m.lowWithin4h > 0) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

private fun rate(v: Double) = String.format(Locale.getDefault(), "%.2f", v)
private fun signed(v: Double) = String.format(Locale.getDefault(), "%+.0f", v)

/** How often the closed loop ran above or below the profile basal, overall and by time of day. */
@Composable
private fun BasalSection(b: BasalComparisonResult, profileChanges: List<app.bganalyzer.domain.EffectiveProfile>) {
    Text(stringResource(R.string.basal_title), style = MaterialTheme.typography.titleMedium)
    Text(stringResource(R.string.basal_intro), style = MaterialTheme.typography.bodySmall)
    if (b.loopCoveragePct < 70) {
        Text(stringResource(R.string.basal_low_coverage, pct(b.loopCoveragePct)), color = MaterialTheme.colorScheme.error)
    } else {
        Text(stringResource(R.string.basal_coverage, pct(b.loopCoveragePct)), style = MaterialTheme.typography.bodySmall)
    }
    ProfileChangesCard(profileChanges)
    val o = b.overall
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.basal_overall), style = MaterialTheme.typography.titleSmall)
            if (!o.enoughDays) {
                Text(stringResource(R.string.patterns_not_enough, o.days, TimeBlocks.MIN_DAYS))
                return@Column
            }
            Text(stringResource(R.string.patterns_days, o.days), style = MaterialTheme.typography.bodySmall)
            BasalLines(o)
            Text(stringResource(R.string.basal_per_day, rate(o.avgActual * 24), rate(o.avgScheduled * 24)))
            if (b.tempCount > 0) {
                Text(
                    stringResource(R.string.basal_temp_count, b.tempCount, rate(b.tempCount / b.periodDays), b.tempAbove, b.tempBelow, b.tempAt),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
    b.blocks.forEach { blk ->
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(stringResource(R.string.patterns_block_time, hour(blk.startHour), hour(blk.endHour)), style = MaterialTheme.typography.titleSmall)
                if (!blk.enoughDays) {
                    Text(stringResource(R.string.patterns_not_enough, blk.days, TimeBlocks.MIN_DAYS))
                } else {
                    Text(stringResource(R.string.patterns_days, blk.days), style = MaterialTheme.typography.bodySmall)
                    BasalLines(blk)
                }
            }
        }
    }
}

@Composable
private fun BasalLines(s: BasalBlockStats) {
    Text(stringResource(R.string.basal_above, pct(s.abovePct)))
    Text(stringResource(R.string.basal_below, pct(s.belowPct)) + if (s.zeroPct >= 0.5) " " + stringResource(R.string.basal_zero, pct(s.zeroPct)) else "")
    Text(stringResource(R.string.basal_at, pct(s.atPct)))
    Text(stringResource(R.string.basal_average, rate(s.avgActual), rate(s.avgScheduled), signed(s.changePct)))
}

/** Which profile was switched to and when, with any percentage or time shift, so the comparison above can be read against it. */
@Composable
private fun ProfileChangesCard(changes: List<app.bganalyzer.domain.EffectiveProfile>) {
    val fmt = androidx.compose.runtime.remember { java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.SHORT) }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.profile_changes_title), style = MaterialTheme.typography.titleSmall)
            if (changes.isEmpty()) {
                Text(stringResource(R.string.profile_changes_none), style = MaterialTheme.typography.bodySmall)
            } else {
                changes.takeLast(15).reversed().forEach {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(fmt.format(java.util.Date(it.startMs)), style = MaterialTheme.typography.bodyMedium)
                        Text(it.label(), style = MaterialTheme.typography.bodyMedium)
                    }
                }
                if (changes.size > 15) Text(stringResource(R.string.profile_changes_more, changes.size - 15), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

/** Advisory ideas only: the app never changes a setting. Each shows its evidence, and held-back ones say why. */
@Composable
private fun SuggestionsSection(state: PatternsState, syncing: Boolean) {
    Text(stringResource(R.string.suggestions_title), style = MaterialTheme.typography.titleMedium)
    Text(stringResource(R.string.suggestions_intro), style = MaterialTheme.typography.bodySmall)
    if (state.emptyDays.isNotEmpty()) {
        Text(stringResource(R.string.suggestions_gaps, state.emptyDays.size), color = MaterialTheme.colorScheme.tertiary)
    }
    if (syncing) Text(stringResource(R.string.suggestions_syncing), color = MaterialTheme.colorScheme.tertiary)
    val r = state.suggestions
    if (r.suggestions.isEmpty() && r.held.isEmpty()) Text(stringResource(R.string.suggestions_none))
    r.suggestions.forEach { s ->
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                val what = if (s.kind == app.bganalyzer.domain.SuggestionKind.BASAL) stringResource(R.string.suggestions_basal) else stringResource(R.string.suggestions_carb_ratio)
                Text("$what ${hour(s.startHour)}-${hour(s.endHour)}", style = MaterialTheme.typography.titleSmall)
                val change = stringResource(if (s.moreInsulin) R.string.suggestions_more else R.string.suggestions_less, s.changePct)
                Text(if (s.fromUph != null && s.toUph != null) "$change (${rate(s.fromUph)} -> ${rate(s.toUph)} U/h)" else change)
                Text(stringResource(R.string.suggestions_confidence, s.confidence.name.lowercase().replaceFirstChar { it.uppercase() }), style = MaterialTheme.typography.bodySmall)
                s.detail?.let { Text(it) }
                s.evidence.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
            }
        }
    }
    r.held.forEach { h ->
        val what = if (h.kind == app.bganalyzer.domain.SuggestionKind.BASAL) stringResource(R.string.suggestions_basal) else stringResource(R.string.suggestions_carb_ratio)
        Text(stringResource(R.string.suggestions_held, what, hour(h.startHour), hour(h.endHour), h.reason), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
    }
}

/** Mark days as bad data, e.g. a pump failure with insulin pens in use. Excluded days are left out of every analysis here. */
@Composable
private fun ExcludedDaysSection(state: PatternsState, onExclude: (String, String) -> Unit, onRestore: (String) -> Unit) {
    val already = state.excludedDays.map { it.date }.toSet()
    val candidates = (0 until state.days).map { java.time.LocalDate.now().minusDays(it.toLong()).toString() }.filter { it !in already }
    var picked by androidx.compose.runtime.remember(candidates.firstOrNull()) { androidx.compose.runtime.mutableStateOf(candidates.firstOrNull()) }
    var note by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf("") }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.excluded_title), style = MaterialTheme.typography.titleSmall)
            Text(stringResource(R.string.excluded_intro), style = MaterialTheme.typography.bodySmall)
            if (candidates.isNotEmpty()) {
                Dropdown(
                    label = stringResource(R.string.excluded_day_label),
                    options = candidates,
                    selected = picked ?: candidates.first(),
                    text = { it },
                    onSelect = { picked = it },
                    modifier = Modifier.fillMaxWidth(),
                )
                androidx.compose.material3.OutlinedTextField(
                    value = note, onValueChange = { note = it.take(80) }, singleLine = true,
                    label = { Text(stringResource(R.string.excluded_note_label)) }, modifier = Modifier.fillMaxWidth(),
                )
                androidx.compose.material3.Button(onClick = { onExclude(picked ?: candidates.first(), note.ifBlank { "Pump failure" }); note = "" }) {
                    Text(stringResource(R.string.excluded_button))
                }
            }
            state.excludedDays.forEach { d ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    Text("${d.date}  ${d.note}", Modifier.weight(1f))
                    androidx.compose.material3.TextButton(onClick = { onRestore(d.date) }) { Text(stringResource(R.string.excluded_restore)) }
                }
            }
        }
    }
}

/** What glucose did in the days before and after each profile change. Shows what happened, not why. */
@Composable
private fun ChangesSection(changes: List<app.bganalyzer.domain.ChangeResult>) {
    if (changes.isEmpty()) return
    val fmt = androidx.compose.runtime.remember { java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.SHORT) }
    Text(stringResource(R.string.changes_title), style = MaterialTheme.typography.titleMedium)
    Text(stringResource(R.string.changes_intro), style = MaterialTheme.typography.bodySmall)
    changes.take(10).forEach { c ->
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("${fmt.format(java.util.Date(c.change.startMs))}  ${c.change.label()}", style = MaterialTheme.typography.titleSmall)
                c.basalPerDayBefore?.let { Text(stringResource(R.string.changes_basal, rate(it), rate(c.basalPerDayAfter)), style = MaterialTheme.typography.bodySmall) }
                if (!c.before.enough || !c.after.enough) {
                    Text(stringResource(R.string.changes_not_enough, pct(c.before.days), pct(c.after.days)))
                } else {
                    PeriodLine(stringResource(R.string.changes_before), c.before)
                    PeriodLine(stringResource(R.string.changes_after), c.after)
                }
            }
        }
    }
}

@Composable
private fun PeriodLine(label: String, p: app.bganalyzer.domain.PeriodSummary) {
    val t = p.timeInRange
    Text(stringResource(R.string.changes_line, label, String.format(Locale.getDefault(), "%.1f", p.days), pct(t.inRangePct), pct(t.lowPct + t.veryLowPct), pct(t.highPct + t.veryHighPct)))
}
