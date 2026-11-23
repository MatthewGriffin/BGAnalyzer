package app.bganalyzer.ui

import androidx.compose.foundation.layout.Arrangement
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
    ScreenScaffold(stringResource(R.string.glucose_title)) {
            if (!hasConnection) Text(stringResource(R.string.sync_need_connection))
            Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f)) {
                    when (sync) {
                        is SyncState.Running -> Text(stringResource(R.string.sync_running, sync.stored), style = MaterialTheme.typography.bodySmall)
                        is SyncState.Failed -> Text(stringResource(R.string.sync_failed), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.titleSmall)
                        else -> Text(stringResource(R.string.sync_status_hint), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
