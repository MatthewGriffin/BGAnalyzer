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
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import app.bganalyzer.R
import app.bganalyzer.autotune.AutotuneAdvice
import app.bganalyzer.autotune.AutotuneAdvisor
import app.bganalyzer.autotune.SkippedSummary
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.format
import java.util.Locale

/**
 * Autotune (ported from AndroidAPS) as the app's main advice. Nothing is changed in any profile: the tables show what
 * to type into a new one, with rows ruled off and values rounded to what a pump and the profile editor accept.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AutotuneScreen(
    state: AutotuneState,
    unit: GlucoseUnit,
    days: Int,
    onDays: (Int) -> Unit,
    peak: Int,
    sync: SyncState,
    onPeak: (Int) -> Unit,
    onRun: (Int) -> Unit,
    onClear: () -> Unit,
    dayQuality: DayQualityState,
    onExcludeDay: (String, String) -> Unit,
    onRestoreDay: (String) -> Unit,
    onExcludeDays: (List<String>, String) -> Unit,
) {
    ScreenScaffold(stringResource(R.string.autotune_title)) {
            if (sync is SyncState.Running) Text(stringResource(R.string.autotune_syncing), color = MaterialTheme.colorScheme.tertiary)
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Dropdown(
                    label = stringResource(R.string.autotune_days_label),
                    options = AutotuneViewModel.DAY_CHOICES, selected = days,
                    text = { stringResource(R.string.range_days, it) },
                    onSelect = onDays, modifier = Modifier.weight(1f),
                )
                Dropdown(
                    label = stringResource(R.string.autotune_insulin_short_label),
                    options = AutotuneViewModel.INSULIN_PEAKS, selected = peak,
                    text = { stringResource(when (it) { 55 -> R.string.autotune_insulin_ultra_short; 45 -> R.string.autotune_insulin_lyumjev_short; else -> R.string.autotune_insulin_rapid_short }) },
                    onSelect = onPeak, modifier = Modifier.weight(1f),
                )
            }
            Button(onClick = { onRun(days) }, enabled = state !is AutotuneState.Running) { Text(stringResource(R.string.autotune_run)) }
            when (state) {
                AutotuneState.Idle -> Text(stringResource(R.string.autotune_idle), style = MaterialTheme.typography.bodySmall)
                is AutotuneState.Running -> Text(stringResource(R.string.autotune_running, state.day, state.of))
                is AutotuneState.Failed -> Text(state.message, color = MaterialTheme.colorScheme.error)
                is AutotuneState.Done -> AutotuneResultCards(state, unit, onClear)
            }
            // data quality last: the advice above is what this tab is for
            ExcludedDaysCards(days, dayQuality.excluded, dayQuality.noInsulinDays, onExcludeDay, onRestoreDay, onExcludeDays)
        }
}

private fun rate(v: Double) = String.format(Locale.getDefault(), "%.2f", v)
private fun hourLabel(h: Int) = String.format(Locale.US, "%02d:00", h % 24)

@Composable
private fun AutotuneResultCards(s: AutotuneState.Done, unit: GlucoseUnit, onClear: () -> Unit) {
    val a: AutotuneAdvice = s.advice
    SectionCard(stringResource(R.string.autotune_result_title)) {
        Text(stringResource(R.string.autotune_days_used, a.daysTuned, s.days), style = MaterialTheme.typography.bodyMedium)
        a.swingMgdlPerHour?.let { sw -> a.cvPct?.let { cv ->
            TileRow {
                StatTile(unit.format(sw), stringResource(R.string.tile_swing, unit.label))
                StatTile(String.format(Locale.getDefault(), "%.0f%%", cv), stringResource(R.string.tile_cv))
            }
        } }
        s.profileChangeMs?.let {
            val whenText = java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT).format(java.util.Date(it))
            Text(stringResource(R.string.autotune_since_change, whenText), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (s.result.skipped.isNotEmpty()) {
            GroupLabel(stringResource(R.string.autotune_skipped))
            SkippedSummary.lines(s.result.skipped).forEach { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary) }
        }
    }

    // Insulin sensitivity and carb ratio
    val lowCr = a.mealsUsed < AutotuneAdvisor.MIN_MEALS
    val lowIsf = a.isfPoints < AutotuneAdvisor.MIN_ISF_POINTS
    SectionCard(stringResource(R.string.autotune_isf_cr)) {
        Column {
            val w = listOf(2.2f, 1f, 1f)
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            TableRow(listOf("", stringResource(R.string.autotune_col_now), stringResource(R.string.autotune_col_suggested)), w, header = true)
            TableRow(
                listOf(stringResource(R.string.autotune_row_isf, unit.label), unit.format(a.currentIsf), unit.format(a.tunedIsf)), w,
                colours = listOf(null, null, if (lowIsf) confidenceColor(app.bganalyzer.domain.Confidence.LOW) else confidenceColor(app.bganalyzer.domain.Confidence.HIGH)),
            )
            TableRow(
                listOf(stringResource(R.string.autotune_row_cr), String.format(Locale.getDefault(), "%.1f", a.currentCarbRatio), String.format(Locale.getDefault(), "%.1f", a.tunedCarbRatio)), w,
                colours = listOf(null, null, if (lowCr) confidenceColor(app.bganalyzer.domain.Confidence.LOW) else confidenceColor(app.bganalyzer.domain.Confidence.HIGH)),
            )
            Text(
                stringResource(R.string.autotune_evidence, a.mealsUsed, a.isfPoints) + if (lowCr || lowIsf) " " + stringResource(R.string.autotune_evidence_low) else "",
                style = MaterialTheme.typography.bodySmall, color = if (lowCr || lowIsf) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.padding(top = 6.dp),
            )
            Text(stringResource(R.string.autotune_isf_cr_note), style = MaterialTheme.typography.bodySmall)
        }
    }

    // Basal by hour
    SectionCard(stringResource(R.string.autotune_basal)) {
        Column {
            val hoursSorted = a.hours.sortedBy { it.hour }
            if (hoursSorted.size == 24) {
                BasalStepChart(hoursSorted.map { it.current }, hoursSorted.map { AutotuneAdvisor.roundToPumpStep(it.suggested) })
                Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) { Dot(MaterialTheme.colorScheme.outline); Text(stringResource(R.string.autotune_col_now), style = MaterialTheme.typography.labelSmall) }
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) { Dot(MaterialTheme.colorScheme.primary); Text(stringResource(R.string.autotune_col_suggested), style = MaterialTheme.typography.labelSmall) }
                }
            }
            val w = listOf(1f, 1f, 1.2f, 1f, 0.6f)
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            TableRow(
                listOf(stringResource(R.string.autotune_col_time), stringResource(R.string.autotune_col_now), stringResource(R.string.autotune_col_suggested), stringResource(R.string.autotune_col_change), stringResource(R.string.autotune_col_conf_short)),
                w, header = true,
            )
            a.hours.forEach { h ->
                // the profile as it is; only the suggestion is rounded to what a pump accepts
                val now = h.current
                val sug = AutotuneAdvisor.roundToPumpStep(h.suggested)
                val change = if (now > 0) (sug / now - 1) * 100 else 0.0
                TableRow(
                    listOf(hourLabel(h.hour), rate(now), rate(sug), String.format(Locale.getDefault(), "%+.0f%%", change), "●"), w,
                    colours = listOf(null, null, null, null, confidenceColor(h.confidence)),
                    note = listOfNotNull(
                        h.heldReason?.let { stringResource(R.string.autotune_held, rate(AutotuneAdvisor.roundToPumpStep(h.tuned)), it) },
                        if (h.unsteady && h.swingMgdlPerHour != null) stringResource(R.string.autotune_unsteady, unit.format(h.swingMgdlPerHour), unit.label) else null,
                    ).joinToString(" ").ifEmpty { null },
                )
            }
            val totalNow = a.hours.sumOf { it.current }
            val totalSug = a.hours.sumOf { AutotuneAdvisor.roundToPumpStep(it.suggested) }
            TableRow(listOf(stringResource(R.string.autotune_total), rate(totalNow), rate(totalSug), String.format(Locale.getDefault(), "%+.0f%%", if (totalNow > 0) (totalSug / totalNow - 1) * 100 else 0.0), ""), w, header = true)
            Text(stringResource(R.string.autotune_conf_legend), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
            Text(stringResource(R.string.autotune_basal_note), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
        }
    }

    TextButton(onClick = onClear) { Text(stringResource(R.string.autotune_clear)) }
}
