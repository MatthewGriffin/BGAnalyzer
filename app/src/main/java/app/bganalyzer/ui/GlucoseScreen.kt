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
    Scaffold(topBar = { TopAppBar(title = { Text(stringResource(R.string.glucose_title)) }) }) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (!hasConnection) Text(stringResource(R.string.sync_need_connection))
            Button(onClick = onSync, enabled = hasConnection && sync !is SyncState.Running) {
                Text(stringResource(R.string.sync_button))
            }
            if (state.unsyncedMs > 60 * 60 * 1000L && sync !is SyncState.Running) {
                Text(stringResource(R.string.sync_unsynced_notice), color = MaterialTheme.colorScheme.tertiary, style = MaterialTheme.typography.bodyMedium)
            }
            when (sync) {
                is SyncState.Running -> {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    Text(stringResource(R.string.sync_running, sync.stored))
                }
                is SyncState.Done -> Text(stringResource(R.string.sync_done, sync.glucose, sync.treatments, sync.iob, sync.spans))
                is SyncState.Failed -> {
                    Text(stringResource(R.string.sync_failed), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.titleSmall)
                    Text(sync.message)
                }
                SyncState.Idle -> Unit
            }

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
                Text(stringResource(R.string.tir_title), style = MaterialTheme.typography.titleMedium)
                TirRow(stringResource(R.string.tir_in_range, unit.format(ranges.lowBelow), unit.format(ranges.highAbove)), tir.inRangePct, Color(0xFF2E9E5B))
                TirRow(stringResource(R.string.tir_high, unit.format(ranges.highAbove), unit.format(ranges.veryHighAbove)), tir.highPct, Color(0xFFE0A030))
                TirRow(stringResource(R.string.tir_very_high, unit.format(ranges.veryHighAbove)), tir.veryHighPct, Color(0xFFD9822B))
                TirRow(stringResource(R.string.tir_low, unit.format(ranges.veryLowBelow), unit.format(ranges.lowBelow)), tir.lowPct, Color(0xFFD64545))
                TirRow(stringResource(R.string.tir_very_low, unit.format(ranges.veryLowBelow)), tir.veryLowPct, Color(0xFF9B1C1C))
                Text(stringResource(R.string.stat_average, unit.format(tir.meanMgdl), unit.label))
                Text(stringResource(R.string.stat_readings, tir.count, coverage), style = MaterialTheme.typography.bodySmall)
                if (coverage < 70) {
                    Text(stringResource(R.string.stat_low_coverage), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
            }
            TreatmentsSection(state)
        }
    }
}

@Composable
private fun TreatmentsSection(state: GlucoseUiState) {
    Text(stringResource(R.string.treat_title), style = MaterialTheme.typography.titleMedium)
    if (state.treatments.isEmpty()) {
        Text(stringResource(R.string.treat_none))
        return
    }
    val days = state.days.toDouble()
    fun one(v: Double) = String.format(Locale.getDefault(), "%.1f", v)
    Text(stringResource(R.string.treat_meals, state.mealCount, one(state.carbsTotal / days)))
    Text(stringResource(R.string.treat_insulin, one(state.bolusInsulinTotal), one(state.bolusInsulinTotal / days)))
    Text(stringResource(R.string.treat_recent), style = MaterialTheme.typography.titleSmall)
    val fmt = remember { java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.SHORT) }
    state.treatments.filter { (it.carbs ?: 0.0) > 0 || (it.insulin ?: 0.0) > 0 }.takeLast(20).reversed().forEach { t ->
        val parts = buildList {
            t.carbs?.takeIf { it > 0 }?.let { add(stringResource(R.string.treat_carbs, one(it))) }
            t.insulin?.takeIf { it > 0 }?.let { add(stringResource(if (t.isSmb) R.string.treat_smb else R.string.treat_units, String.format(Locale.getDefault(), "%.2f", it))) }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(fmt.format(java.util.Date(t.timestampMs)), style = MaterialTheme.typography.bodyMedium)
            Text(parts.joinToString("  "), style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
private fun periodText(days: Int) =
    if (days == 1) stringResource(R.string.range_one_day) else stringResource(R.string.range_days, days)

@Composable
private fun TirRow(label: String, percent: Double, color: Color) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(label)
            Text(stringResource(R.string.tir_percent, String.format(Locale.getDefault(), "%.1f", percent)))
        }
        LinearProgressIndicator(
            progress = { (percent / 100).toFloat() },
            color = color,
            gapSize = 0.dp,
            drawStopIndicator = {},
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

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
