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
) {
    ScreenScaffold(stringResource(R.string.autotune_title)) {
            Text(stringResource(R.string.autotune_intro), style = MaterialTheme.typography.bodySmall)
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
        }
}

private fun rate(v: Double) = String.format(Locale.getDefault(), "%.2f", v)
private fun hourLabel(h: Int) = String.format(Locale.US, "%02d:00", h % 24)

/** One table row: cells share the width by weight, and a rule is drawn under it. */
@Composable
private fun TableRow(cells: List<String>, weights: List<Float>, header: Boolean = false, colours: List<androidx.compose.ui.graphics.Color?> = emptyList(), note: String? = null) {
    Column(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            cells.forEachIndexed { i, text ->
                Text(
                    text, Modifier.weight(weights[i]),
                    textAlign = if (i == 0) TextAlign.Start else TextAlign.End,
                    fontWeight = if (header || i == 2) FontWeight.Bold else FontWeight.Normal,
                    style = if (header) MaterialTheme.typography.labelMedium else MaterialTheme.typography.bodyMedium,
                    color = colours.getOrNull(i) ?: MaterialTheme.colorScheme.onSurface,
                )
            }
        }
        note?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(bottom = 6.dp)) }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

@Composable
private fun AutotuneResultCards(s: AutotuneState.Done, unit: GlucoseUnit, onClear: () -> Unit) {
    val a: AutotuneAdvice = s.advice
    Text(stringResource(R.string.autotune_days_used, a.daysTuned, s.days), style = MaterialTheme.typography.bodySmall)
    if (s.result.skipped.isNotEmpty()) {
        Column {
            Text(stringResource(R.string.autotune_skipped), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.tertiary)
            SkippedSummary.lines(s.result.skipped).forEach { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary) }
        }
    }

    // Insulin sensitivity and carb ratio
    val lowCr = a.mealsUsed < AutotuneAdvisor.MIN_MEALS
    val lowIsf = a.isfPoints < AutotuneAdvisor.MIN_ISF_POINTS
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Text(stringResource(R.string.autotune_isf_cr), style = MaterialTheme.typography.titleSmall)
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
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Text(stringResource(R.string.autotune_basal), style = MaterialTheme.typography.titleSmall)
            val w = listOf(1f, 1f, 1.2f, 1f, 1.1f)
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            TableRow(
                listOf(stringResource(R.string.autotune_col_time), stringResource(R.string.autotune_col_now), stringResource(R.string.autotune_col_suggested), stringResource(R.string.autotune_col_change), stringResource(R.string.autotune_col_confidence)),
                w, header = true,
            )
            a.hours.forEach { h ->
                // the profile as it is; only the suggestion is rounded to what a pump accepts
                val now = h.current
                val sug = AutotuneAdvisor.roundToPumpStep(h.suggested)
                val change = if (now > 0) (sug / now - 1) * 100 else 0.0
                TableRow(
                    listOf(hourLabel(h.hour), rate(now), rate(sug), String.format(Locale.getDefault(), "%+.0f%%", change), h.confidence.name.lowercase()), w,
                    colours = listOf(null, null, null, null, confidenceColor(h.confidence)),
                    note = h.heldReason?.let { stringResource(R.string.autotune_held, rate(AutotuneAdvisor.roundToPumpStep(h.tuned)), it) },
                )
            }
            val totalNow = a.hours.sumOf { it.current }
            val totalSug = a.hours.sumOf { AutotuneAdvisor.roundToPumpStep(it.suggested) }
            TableRow(listOf(stringResource(R.string.autotune_total), rate(totalNow), rate(totalSug), String.format(Locale.getDefault(), "%+.0f%%", if (totalNow > 0) (totalSug / totalNow - 1) * 100 else 0.0), ""), w, header = true)
            Text(stringResource(R.string.autotune_basal_note), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
        }
    }

    // The same suggested basal as profile entries
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Text(stringResource(R.string.autotune_blocks), style = MaterialTheme.typography.titleSmall)
            Text(stringResource(R.string.autotune_blocks_note), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(bottom = 4.dp))
            val w = listOf(1.6f, 1f)
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            TableRow(listOf(stringResource(R.string.autotune_col_time), stringResource(R.string.autotune_col_rate)), w, header = true)
            AutotuneAdvisor.blocks(a.hours).forEach { b ->
                TableRow(listOf("${hourLabel(b.startHour)} - ${hourLabel(b.endHour)}", rate(b.rate)), w, colours = listOf(null, null))
            }
        }
    }
    TextButton(onClick = onClear) { Text(stringResource(R.string.autotune_clear)) }
}
