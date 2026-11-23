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
import androidx.compose.ui.text.withStyle
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
) {
    ScreenScaffold(stringResource(R.string.patterns_title)) {
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
            if (state.loaded && state.readingCount == 0) {
                EmptyDaysNotice(state.emptyDays)
                Text(stringResource(R.string.patterns_no_data))
                return@ScreenScaffold
            }
            if (state.zoneName.isNotEmpty()) Text(stringResource(R.string.patterns_timezone, state.zoneName), style = MaterialTheme.typography.bodySmall)
            state.basal?.let { BasalHeader(it) }
            state.basal?.let { OverallBasalCard(it) }
            state.blocks.forEach { g ->
                TimeBlockCard(g, state.basal?.blocks?.firstOrNull { it.startHour == g.startHour }, state.meals.firstOrNull { it.startHour == g.startHour }, unit)
            }
            Text(stringResource(R.string.patterns_meals_intro), style = MaterialTheme.typography.bodySmall)
            ChangesTimeline(state, unit)
            ProfileHistorySection(state.profileHistory, unit)
            // data quality last: the trends above are what this tab is for
            EmptyDaysNotice(state.emptyDays)
        }
}

private fun hour(h: Int) = String.format(Locale.US, "%02d:00", h % 24)
private fun pct(v: Double) = String.format(Locale.getDefault(), "%.0f", v)

/** One time of day: glucose, the loop's basal against the profile, and glucose after meals, in one card. */
@Composable
private fun TimeBlockCard(g: BlockStats, basal: BasalBlockStats?, meal: MealBlockStats?, unit: GlucoseUnit) {
    SectionCard(null) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.patterns_block_time, hour(g.startHour), hour(g.endHour)), style = MaterialTheme.typography.titleMedium)
            Section(stringResource(R.string.patterns_glucose_title)) { GlucoseLines(g, unit) }
            basal?.let { Section(stringResource(R.string.basal_title)) { BasalBlockLines(it) } }
            meal?.let { Section(stringResource(R.string.patterns_meals_title)) { MealLines(it, unit) } }
        }
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Text(title, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 8.dp))
    content()
}

@Composable
private fun GlucoseLines(b: BlockStats, unit: GlucoseUnit) {
    if (!b.enoughDays) {
        Text(stringResource(R.string.patterns_not_enough, b.days, TimeBlocks.MIN_DAYS))
        return
    }
    val tir = b.timeInRange
    Text(stringResource(R.string.patterns_days, b.days), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    RangeBar(tir, Modifier.padding(vertical = 4.dp))
    Row(Modifier.fillMaxWidth()) {
        RangeLegend(stringResource(R.string.tir_short_low), tir.lowPct + tir.veryLowPct, glucoseColor(GlucoseBand.LOW))
        RangeLegend(stringResource(R.string.patterns_short_in_range), tir.inRangePct, glucoseColor(GlucoseBand.IN_RANGE))
        RangeLegend(stringResource(R.string.tir_short_high), tir.highPct + tir.veryHighPct, glucoseColor(GlucoseBand.HIGH))
    }
    FactRow(stringResource(R.string.patterns_fact_average), unit.format(tir.meanMgdl) + " " + unit.label)
    b.swingMgdlPerHour?.let { FactRow(stringResource(R.string.patterns_fact_swing), unit.format(it) + " " + unit.label + "/h  ·  CV " + pct(tir.cvPct) + "%") }
    if (b.lowDays > 0) Text(stringResource(R.string.patterns_low_days, b.lowDays, b.days), color = glucoseColor(GlucoseBand.LOW))
    if (b.veryLowDays > 0) Text(stringResource(R.string.patterns_very_low_days, b.veryLowDays, b.days), color = glucoseColor(GlucoseBand.VERY_LOW))
}

@Composable
private fun BasalBlockLines(blk: BasalBlockStats) {
    if (!blk.enoughDays) {
        Text(stringResource(R.string.patterns_not_enough, blk.days, TimeBlocks.MIN_DAYS))
    } else {
        BasalLines(blk)
    }
}

@Composable
private fun MealLines(m: MealBlockStats, unit: GlucoseUnit) {
    if (m.meals == 0) {
        Text(stringResource(R.string.patterns_meals_count, 0))
        return
    }
    if (!m.enoughMeals) {
        Text(stringResource(R.string.patterns_meals_not_enough, m.meals, PostMeal.MIN_MEALS))
        return
    }
    Text(stringResource(R.string.patterns_meals_count, m.meals), style = MaterialTheme.typography.bodySmall)
    // A rise is a difference, so it converts without an offset.
    Text(stringResource(R.string.patterns_meal_rise, unit.format(m.medianRiseMgdl), unit.label))
    m.medianAt2hMgdl?.let { Text(stringResource(R.string.patterns_meal_2h, unit.format(it), unit.label)) }
    if (m.withReading2h > 0) Text(stringResource(R.string.patterns_meal_high2h, m.highAt2h, m.withReading2h), color = if (m.highAt2h > 0) glucoseColor(GlucoseBand.HIGH) else MaterialTheme.colorScheme.onSurface)
    Text(
        stringResource(R.string.patterns_meal_low4h, m.lowWithin4h, m.meals),
        color = if (m.lowWithin4h > 0) glucoseColor(GlucoseBand.LOW) else MaterialTheme.colorScheme.onSurface,
    )
}

private fun rate(v: Double) = String.format(Locale.getDefault(), "%.2f", v)
private fun signed(v: Double) = String.format(Locale.getDefault(), "%+.0f", v)

/** What the loop-basal comparison below means, and how much of the period the loop was running. */
@Composable
private fun BasalHeader(b: BasalComparisonResult) {
    Text(stringResource(R.string.basal_intro), style = MaterialTheme.typography.bodySmall)
    if (b.loopCoveragePct < 70) {
        Text(stringResource(R.string.basal_low_coverage, pct(b.loopCoveragePct)), color = MaterialTheme.colorScheme.error)
    } else {
        Text(stringResource(R.string.basal_coverage, pct(b.loopCoveragePct)), style = MaterialTheme.typography.bodySmall)
    }
}

/** The whole day: how often the loop ran above or below the profile basal, and the total per day. */
@Composable
private fun OverallBasalCard(b: BasalComparisonResult) {
    val o = b.overall
    SectionCard(null) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.basal_overall), style = MaterialTheme.typography.titleMedium)
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
}

@Composable
private fun BasalLines(s: BasalBlockStats) {
    Text(stringResource(R.string.basal_above, pct(s.abovePct)))
    Text(stringResource(R.string.basal_below, pct(s.belowPct)) + if (s.zeroPct >= 0.5) " " + stringResource(R.string.basal_zero, pct(s.zeroPct)) else "")
    Text(stringResource(R.string.basal_at, pct(s.atPct)))
    Text(stringResource(R.string.basal_average, rate(s.avgActual), rate(s.avgScheduled), signed(s.changePct)))
}

/**
 * Everything that changed in the period, newest first, in one list: profile switches, and site, insulin and sensor
 * changes, each with glucose before and after it. Shows what happened, not why.
 */
@Composable
private fun ChangesTimeline(state: PatternsState, unit: GlucoseUnit) {
    val fmt = androidx.compose.runtime.remember { java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.SHORT) }
    val entries = buildList {
        state.changes.forEach { add(TimelineEntry(it.change.startMs, "Profile: " + it.change.label(), it.basalPerDayBefore, it.basalPerDayAfter, it.before, it.after)) }
        state.equipment.forEach { add(TimelineEntry(it.change.startMs, it.change.label, null, null, it.before, it.after)) }
    }
        // Only changes with glucose to compare on both sides are worth a card
        .filter { it.before?.enough == true && it.after?.enough == true }
        // One card per day, anchored at the day's most recent change; the others that day are named in its title
        .let { all ->
            val zone = runCatching { java.time.ZoneId.of(state.zoneName) }.getOrDefault(java.time.ZoneId.systemDefault())
            all.groupBy { java.time.LocalDate.ofInstant(java.time.Instant.ofEpochMilli(it.timeMs), zone) }.values.map { day ->
                val byTime = day.sortedBy { it.timeMs }
                val latest = byTime.last()
                latest.copy(label = byTime.map { it.label }.distinct().joinToString(", "))
            }
        }
        .sortedByDescending { it.timeMs }
    Text(stringResource(R.string.timeline_title), style = MaterialTheme.typography.titleMedium)
    if (entries.isEmpty()) {
        Text(stringResource(R.string.timeline_none), style = MaterialTheme.typography.bodySmall)
        return
    }
    Text(stringResource(R.string.timeline_intro), style = MaterialTheme.typography.bodySmall)
    entries.take(15).forEach { e ->
        SectionCard(null) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(fmt.format(java.util.Date(e.timeMs)), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                Text(e.label, style = MaterialTheme.typography.titleSmall)
                e.basalBefore?.let { Text(stringResource(R.string.changes_basal, rate(it), rate(e.basalAfter ?: it)), style = MaterialTheme.typography.bodySmall) }
                e.before?.let { PeriodLine(stringResource(R.string.changes_before), it); StabilityLine(it.swingMgdlPerHour, it.timeInRange.cvPct, unit) }
                e.after?.let { PeriodLine(stringResource(R.string.changes_after), it); StabilityLine(it.swingMgdlPerHour, it.timeInRange.cvPct, unit) }
                if (e.before != null && e.after != null) StabilityVerdict(e.before, e.after)
            }
        }
    }
    if (entries.size > 15) Text(stringResource(R.string.profile_changes_more, entries.size - 15), style = MaterialTheme.typography.bodySmall)
}

private data class TimelineEntry(
    val timeMs: Long, val label: String,
    val basalBefore: Double?, val basalAfter: Double?,
    val before: app.bganalyzer.domain.PeriodSummary?, val after: app.bganalyzer.domain.PeriodSummary?,
)

@Composable
private fun PeriodLine(label: String, p: app.bganalyzer.domain.PeriodSummary) {
    val t = p.timeInRange
    val green = glucoseColor(GlucoseBand.IN_RANGE); val red = glucoseColor(GlucoseBand.LOW); val orange = glucoseColor(GlucoseBand.HIGH)
    RangeBar(t, Modifier.padding(top = 4.dp))
    val head = stringResource(R.string.changes_line_head, label, String.format(Locale.getDefault(), "%.1f", p.days))
    val inRange = stringResource(R.string.changes_in_range, pct(t.inRangePct))
    val below = stringResource(R.string.changes_below, pct(t.lowPct + t.veryLowPct))
    val above = stringResource(R.string.changes_above, pct(t.highPct + t.veryHighPct))
    Text(androidx.compose.ui.text.buildAnnotatedString {
        append(head); append(' ')
        withStyle(androidx.compose.ui.text.SpanStyle(color = green)) { append(inRange) }
        append(", ")
        withStyle(androidx.compose.ui.text.SpanStyle(color = red)) { append(below) }
        append(", ")
        withStyle(androidx.compose.ui.text.SpanStyle(color = orange)) { append(above) }
    })
}

/**
 * Every profile configuration that took effect, newest first, each with the glucose it saw and, on request, its settings,
 * so one that turned out worse can be read back and typed into AAPS again.
 */
@Composable
private fun ProfileHistorySection(history: List<app.bganalyzer.domain.ProfileConfig>, unit: GlucoseUnit) {
    if (history.isEmpty()) return
    val fmt = androidx.compose.runtime.remember { java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT) }
    Text(stringResource(R.string.history_title), style = MaterialTheme.typography.titleMedium)
    Text(stringResource(R.string.history_intro), style = MaterialTheme.typography.bodySmall)
    history.forEachIndexed { i, c ->
        var open by androidx.compose.runtime.saveable.rememberSaveable(c.profile.startMs) { androidx.compose.runtime.mutableStateOf(false) }
        SectionCard(null) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    fmt.format(java.util.Date(c.profile.startMs)) + " – " + (c.endMs?.let { fmt.format(java.util.Date(it)) } ?: stringResource(R.string.history_now)),
                    style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary,
                )
                Text(
                    c.profile.label() + if (i == 0) " " + stringResource(R.string.history_current) else "",
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(stringResource(R.string.history_basal_total, rate(app.bganalyzer.domain.ChangeComparison.totalBasal(c.profile.basal))), style = MaterialTheme.typography.bodySmall)
                val s = c.summary
                if (s.readings > 0 && s.days >= 0.5) {
                    PeriodLine(stringResource(R.string.history_glucose), s)
                    StabilityLine(s.swingMgdlPerHour, s.timeInRange.cvPct, unit)
                } else {
                    Text(stringResource(R.string.history_no_glucose), style = MaterialTheme.typography.bodySmall)
                }
                androidx.compose.material3.TextButton(onClick = { open = !open }) {
                    Text(stringResource(if (open) R.string.history_hide else R.string.history_show))
                }
                if (open) ProfileSettingsTable(c.profile, unit)
            }
        }
    }
}

/** The profile as one ruled table, like the Autotune tables: from-time, basal, ISF and carb ratio, then the totals. */
@Composable
private fun ProfileSettingsTable(p: app.bganalyzer.domain.EffectiveProfile, unit: GlucoseUnit) {
    fun time(sec: Int) = String.format(Locale.US, "%02d:%02d", sec / 3600 % 24, sec / 60 % 60)
    val st = p.settings
    // every time any schedule changes, with the value of each schedule in force from there
    val starts = (p.basal.map { it.secondsFromMidnight } + st.isf.map { it.secondsFromMidnight } + st.carbRatio.map { it.secondsFromMidnight } + 0).distinct().sorted()
    fun at(steps: List<app.bganalyzer.domain.BasalStep>, sec: Int) = (steps.sortedBy { it.secondsFromMidnight }.lastOrNull { it.secondsFromMidnight <= sec } ?: steps.minByOrNull { it.secondsFromMidnight })?.rateUph
    val w = listOf(1f, 1f, 1f, 1f)
    androidx.compose.material3.HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    TableRow(listOf(stringResource(R.string.autotune_col_time), stringResource(R.string.history_col_basal), stringResource(R.string.history_col_isf, unit.label), stringResource(R.string.history_col_cr)), w, header = true)
    starts.forEach { sec ->
        TableRow(
            listOf(
                time(sec), at(p.basal, sec)?.let { rate(it) } ?: "-",
                at(st.isf, sec)?.let { unit.format(it) } ?: "-",
                at(st.carbRatio, sec)?.let { String.format(Locale.getDefault(), "%.2f", it) } ?: "-",
            ),
            w, boldColumn = -1,
        )
    }
    TableRow(listOf(stringResource(R.string.autotune_total), rate(app.bganalyzer.domain.ChangeComparison.totalBasal(p.basal)), "", ""), w, header = true)
    st.diaHours?.let { Text(stringResource(R.string.history_dia, String.format(Locale.getDefault(), "%.1f", it)), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp)) }
    if (st.isf.isEmpty() && st.carbRatio.isEmpty()) Text(stringResource(R.string.history_no_settings), style = MaterialTheme.typography.bodySmall)
}
