package app.bganalyzer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.clickable
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.bganalyzer.R
import app.bganalyzer.domain.GlucoseRanges
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.coveragePercent
import app.bganalyzer.domain.format
import java.util.Locale

private val PERIODS = listOf(1, 7, 14, 30, 90)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GlucoseScreen(
    state: GlucoseUiState,
    sync: SyncState,
    hasConnection: Boolean,
    onDaysChange: (Int) -> Unit,
    onUnitChange: (GlucoseUnit) -> Unit,
    onLayoutChange: (ChartLayout) -> Unit,
    onSync: () -> Unit,
) {
    val ranges = GlucoseRanges()
    val unit = state.unit
    ScreenScaffold(stringResource(R.string.glucose_title), onRefresh = if (hasConnection) onSync else null, refreshing = sync is SyncState.Running) {
            if (!hasConnection) Text(stringResource(R.string.sync_need_connection))
            Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f)) {
                    when (sync) {
                        is SyncState.Running -> Text(stringResource(R.string.sync_running, sync.stored), style = MaterialTheme.typography.bodySmall)
                        is SyncState.Failed -> Text(stringResource(R.string.sync_failed), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.titleSmall)
                        else -> Text(lastSyncedText(sync), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                androidx.compose.material3.FilledTonalButton(onClick = onSync, enabled = hasConnection && sync !is SyncState.Running) {
                    Text(stringResource(R.string.sync_button))
                }
            }
            if (sync is SyncState.Running) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (sync is SyncState.Failed) Text(sync.message)
            if (hasConnection && state.unsyncedMs > 60 * 60 * 1000L && sync !is SyncState.Running) {
                Text(stringResource(R.string.sync_unsynced_notice), color = MaterialTheme.colorScheme.tertiary, style = MaterialTheme.typography.bodySmall)
            }
            EmptyDaysNotice(state.emptyDays)

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Dropdown(
                    label = stringResource(R.string.range_label),
                    options = PERIODS,
                    selected = state.days,
                    text = { periodText(it) },
                    onSelect = onDaysChange,
                    modifier = Modifier.weight(1f),
                )
                Dropdown(
                    label = stringResource(R.string.unit_label),
                    options = GlucoseUnit.entries,
                    selected = unit,
                    text = { it.label },
                    onSelect = onUnitChange,
                    modifier = Modifier.weight(1f),
                )
            }

            Dropdown(
                label = stringResource(R.string.layout_label),
                options = ChartLayout.entries,
                selected = state.layout,
                text = { stringResource(if (it == ChartLayout.OVERLAID) R.string.layout_overlaid else R.string.layout_separate) },
                onSelect = onLayoutChange,
                modifier = Modifier.fillMaxWidth(0.5f),
            )

            if (state.points.isEmpty()) {
                Text(stringResource(R.string.chart_no_data))
            } else {
                GlucoseCharts(state, ranges)
                val tir = state.timeInRange
                val coverage = coveragePercent(tir.count, state.toMs - state.fromMs)
                SectionCard(stringResource(R.string.tir_title)) {
                    Row(verticalAlignment = androidx.compose.ui.Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(String.format(Locale.getDefault(), "%.0f%%", tir.inRangePct), style = MaterialTheme.typography.displaySmall, color = glucoseColor(GlucoseBand.IN_RANGE))
                        Text(stringResource(R.string.tir_in_range_caption, unit.format(ranges.lowBelow), unit.format(ranges.highAbove), unit.label), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(bottom = 6.dp))
                    }
                    RangeBar(tir)
                    Row(Modifier.fillMaxWidth()) {
                        RangeLegend(stringResource(R.string.tir_short_very_low), tir.veryLowPct, glucoseColor(GlucoseBand.VERY_LOW))
                        RangeLegend(stringResource(R.string.tir_short_low), tir.lowPct, glucoseColor(GlucoseBand.LOW))
                        RangeLegend(stringResource(R.string.tir_short_high), tir.highPct, glucoseColor(GlucoseBand.HIGH))
                        RangeLegend(stringResource(R.string.tir_short_very_high), tir.veryHighPct, glucoseColor(GlucoseBand.VERY_HIGH))
                    }
                    Text(stringResource(R.string.tir_bands_note, unit.format(ranges.veryLowBelow), unit.format(ranges.lowBelow), unit.format(ranges.highAbove), unit.format(ranges.veryHighAbove)), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                DailySection(state)
                LowsSection(state)
                val swing = androidx.compose.runtime.remember(state.points) { app.bganalyzer.domain.Swing.of(state.points).perHour }
                TileRow {
                    StatTile(unit.format(tir.meanMgdl), stringResource(R.string.tile_average, unit.label))
                    if (swing != null) StatTile(unit.format(swing), stringResource(R.string.tile_swing, unit.label))
                    StatTile(String.format(Locale.getDefault(), "%.0f%%", tir.cvPct), stringResource(R.string.tile_cv))
                }
                Text(stringResource(R.string.stat_readings, tir.count, coverage), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (coverage < 70) {
                    Text(stringResource(R.string.stat_low_coverage), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
            }
            TreatmentsSection(state)
        }
}

@Composable
private fun TreatmentsSection(state: GlucoseUiState) {
    SectionCard(stringResource(R.string.treat_title)) {
        if (state.treatments.isEmpty()) {
            Text(stringResource(R.string.treat_none), style = MaterialTheme.typography.bodyMedium)
            return@SectionCard
        }
        val days = state.days.toDouble()
        fun one(v: Double) = String.format(Locale.getDefault(), "%.1f", v)
        TileRow {
            StatTile(state.mealCount.toString(), stringResource(R.string.tile_meals))
            StatTile(one(state.carbsTotal / days), stringResource(R.string.tile_carbs_day))
            StatTile(one(state.bolusInsulinTotal / days), stringResource(R.string.tile_bolus_day))
        }
        Text(stringResource(R.string.treat_bolus_note), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun periodText(days: Int) =
    if (days == 1) stringResource(R.string.range_one_day) else stringResource(R.string.range_days, days)

/** A choice between options is always a dropdown in this app. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun <T> Dropdown(
    label: String,
    options: List<T>,
    selected: T,
    text: @Composable (T) -> String,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded, { expanded = it }, modifier) {
        OutlinedTextField(
            value = text(selected),
            onValueChange = {},
            readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            modifier = Modifier.menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
        )
        ExposedDropdownMenu(expanded, { expanded = false }) {
            options.forEach { option ->
                DropdownMenuItem(text = { Text(text(option)) }, onClick = { onSelect(option); expanded = false })
            }
        }
    }
}

/** "Last synced 14 min ago", or the hint when the app has never synced. Recomputed whenever a sync changes state. */
@Composable
internal fun lastSyncedText(sync: SyncState): String {
    val context = androidx.compose.ui.platform.LocalContext.current
    val last = androidx.compose.runtime.remember(sync) { app.bganalyzer.sync.SyncRunner.lastSyncMs(context) }
    if (last == 0L) return stringResource(R.string.sync_status_hint)
    val ago = android.text.format.DateUtils.getRelativeTimeSpanString(last, System.currentTimeMillis(), android.text.format.DateUtils.MINUTE_IN_MILLIS).toString()
    return stringResource(R.string.sync_last, ago)
}

private fun zoneOf(state: GlucoseUiState): java.time.ZoneId = runCatching { java.time.ZoneId.of(state.zoneId) }.getOrDefault(java.time.ZoneId.systemDefault())

/** One bar per day: the share of readings in range. Tap a day to see it in detail. */
@Composable
private fun DailySection(state: GlucoseUiState) {
    if (state.days < 7) return
    val zone = zoneOf(state)
    val days = androidx.compose.runtime.remember(state.points, state.fromMs, state.toMs) { app.bganalyzer.domain.DailyRange.of(state.points, zone, state.fromMs, state.toMs) }
    var open by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf<String?>(null) }
    SectionCard(stringResource(R.string.daily_title)) {
        Text(stringResource(R.string.daily_hint), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        val fmt = androidx.compose.runtime.remember { java.time.format.DateTimeFormatter.ofPattern("d/M") }
        Row(Modifier.fillMaxWidth().height(110.dp), horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = androidx.compose.ui.Alignment.Bottom) {
            days.forEach { d ->
                val frac = (d.timeInRange.inRangePct / 100).toFloat().coerceIn(0.03f, 1f)
                Column(
                    Modifier.weight(1f).fillMaxHeight().clickable(enabled = d.readings > 0) { open = d.date.toString() },
                    verticalArrangement = Arrangement.Bottom, horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally,
                ) {
                    if (d.readings > 0) androidx.compose.foundation.layout.Box(
                        Modifier.fillMaxWidth().fillMaxHeight(frac).background(
                            glucoseColor(GlucoseBand.IN_RANGE).copy(alpha = if (d.complete) 1f else 0.4f),
                            androidx.compose.foundation.shape.RoundedCornerShape(topStart = 3.dp, topEnd = 3.dp),
                        ),
                    )
                }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(days.first().date.format(fmt), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(days.last().date.format(fmt), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        val good = days.filter { it.complete }
        if (good.size >= 2) {
            val half = good.size / 2
            val early = good.take(half).map { it.timeInRange.inRangePct }.average()
            val late = good.drop(good.size - half).map { it.timeInRange.inRangePct }.average()
            val diff = late - early
            Text(
                when {
                    diff >= 3 -> stringResource(R.string.daily_trend_up, String.format(Locale.getDefault(), "%.0f", diff))
                    diff <= -3 -> stringResource(R.string.daily_trend_down, String.format(Locale.getDefault(), "%.0f", -diff))
                    else -> stringResource(R.string.daily_trend_flat)
                },
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
    open?.let { iso -> days.firstOrNull { it.date.toString() == iso }?.let { DayDialog(state, it, zone) { open = null } } }
}

/** The chosen day on its own: time in range, lows, and the same touch-through chart as the Overview. */
@Composable
private fun DayDialog(state: GlucoseUiState, day: app.bganalyzer.domain.DayStat, zone: java.time.ZoneId, onClose: () -> Unit) {
    val from = day.date.atStartOfDay(zone).toInstant().toEpochMilli()
    val to = day.date.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli()
    val dayState = androidx.compose.runtime.remember(state, day) {
        val pts = state.points.filter { it.timestampMs in from until to }
        val tr = state.treatments.filter { it.timestampMs in from until to }
        state.copy(
            days = 1, points = pts, fromMs = from, toMs = to, treatments = tr, timeInRange = day.timeInRange,
            mealCount = app.bganalyzer.domain.PostMeal.meals(tr).size,
            carbsTotal = app.bganalyzer.domain.PostMeal.meals(tr).sumOf { it.carbs },
            bolusInsulinTotal = tr.sumOf { (it.insulin ?: 0.0).coerceAtLeast(0.0) },
        )
    }
    val unit = state.unit
    val lows = androidx.compose.runtime.remember(dayState) { app.bganalyzer.domain.Lows.summarize(dayState.points, zone) }
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onClose,
        confirmButton = { androidx.compose.material3.TextButton(onClick = onClose) { Text(stringResource(R.string.day_close)) } },
        title = { Text(java.time.format.DateTimeFormatter.ofLocalizedDate(java.time.format.FormatStyle.FULL).format(day.date)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                GlucoseCharts(dayState)
                RangeBar(day.timeInRange)
                TileRow {
                    StatTile(String.format(Locale.getDefault(), "%.0f%%", day.timeInRange.inRangePct), stringResource(R.string.day_in_range), glucoseColor(GlucoseBand.IN_RANGE))
                    StatTile(unit.format(day.timeInRange.meanMgdl), stringResource(R.string.tile_average, unit.label))
                    StatTile(lows.count.toString(), stringResource(R.string.lows_episodes))
                }
                TileRow {
                    StatTile(String.format(Locale.getDefault(), "%.0f", dayState.carbsTotal), stringResource(R.string.day_carbs))
                    StatTile(String.format(Locale.getDefault(), "%.1f", dayState.bolusInsulinTotal), stringResource(R.string.day_bolus))
                    lows.lowestMgdl?.let { StatTile(unit.format(it), stringResource(R.string.lows_lowest), glucoseColor(GlucoseBand.LOW)) }
                }
            }
        },
    )
}

/** How often glucose went low, for how long, and at what time of day. */
@Composable
private fun LowsSection(state: GlucoseUiState) {
    val zone = zoneOf(state)
    val lows = androidx.compose.runtime.remember(state.points) { app.bganalyzer.domain.Lows.summarize(state.points, zone) }
    SectionCard(stringResource(R.string.lows_title)) {
        if (lows.count == 0) {
            Text(stringResource(R.string.lows_none), style = MaterialTheme.typography.bodyMedium)
            return@SectionCard
        }
        TileRow {
            StatTile(lows.count.toString(), stringResource(R.string.lows_episodes), glucoseColor(GlucoseBand.LOW))
            StatTile(stringResource(R.string.lows_minutes_value, lows.averageMinutes), stringResource(R.string.lows_average_length))
            StatTile(state.unit.format(lows.lowestMgdl ?: 0.0), stringResource(R.string.lows_lowest))
        }
        lows.worstHour?.let { h -> Text(stringResource(R.string.lows_worst_hour, String.format(Locale.US, "%02d:00", h), String.format(Locale.US, "%02d:00", (h + 1) % 24)), style = MaterialTheme.typography.bodyMedium) }
        if (lows.veryLowEpisodes > 0) Text(stringResource(R.string.lows_very_low, lows.veryLowEpisodes), style = MaterialTheme.typography.bodyMedium, color = glucoseColor(GlucoseBand.VERY_LOW))
        Text(stringResource(R.string.lows_note), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
