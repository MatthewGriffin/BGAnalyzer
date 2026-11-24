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
    onSync: () -> Unit = {},
) {
    ScreenScaffold(stringResource(R.string.autotune_title), onRefresh = onSync, refreshing = sync is SyncState.Running) {
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
    ActionSummary(a, s.previous)
    SectionCard(stringResource(R.string.autotune_result_title)) {
        Text(stringResource(R.string.autotune_days_used, a.daysTuned, s.days), style = MaterialTheme.typography.bodyMedium)
        if (s.usedFirst != null && s.usedLast != null) {
            val f = java.time.format.DateTimeFormatter.ofPattern("d MMM")
            Text(stringResource(R.string.autotune_window, s.usedFirst.format(f), s.usedLast.format(f)), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
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
            val keep = stringResource(R.string.autotune_keep)
            TableRow(
                listOf(stringResource(R.string.autotune_row_isf, unit.label), unit.format(a.currentIsf), if (lowIsf) keep else unit.format(a.tunedIsf)), w,
                colours = listOf(null, null, if (lowIsf) MaterialTheme.colorScheme.onSurfaceVariant else confidenceColor(app.bganalyzer.domain.Confidence.HIGH)),
                note = if (lowIsf) stringResource(R.string.autotune_isf_too_little, a.isfPoints, AutotuneAdvisor.MIN_ISF_POINTS) else null,
            )
            TableRow(
                listOf(stringResource(R.string.autotune_row_cr), String.format(Locale.getDefault(), "%.1f", a.currentCarbRatio), if (lowCr) keep else String.format(Locale.getDefault(), "%.1f", a.tunedCarbRatio)), w,
                colours = listOf(null, null, if (lowCr) MaterialTheme.colorScheme.onSurfaceVariant else confidenceColor(app.bganalyzer.domain.Confidence.HIGH)),
                note = if (lowCr) stringResource(R.string.autotune_cr_too_little, a.mealsUsed, AutotuneAdvisor.MIN_MEALS) else null,
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
                        if (h.heldReason == null && change >= 10) stringResource(R.string.autotune_why_up) else null,
                        if (h.heldReason == null && change <= -10) stringResource(R.string.autotune_why_down) else null,
                        s.previous?.rates?.getOrNull(h.hour)?.takeIf { kotlin.math.abs(it - sug) >= 0.1 }?.let { stringResource(R.string.autotune_last_run_row, rate(it)) },
                        if (h.limited && h.heldReason == null) stringResource(R.string.autotune_limited) else null,
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

    val context = androidx.compose.ui.platform.LocalContext.current
    val shareText = shareText(a, unit)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = {
            val send = android.content.Intent(android.content.Intent.ACTION_SEND).setType("text/plain").putExtra(android.content.Intent.EXTRA_TEXT, shareText)
            context.startActivity(android.content.Intent.createChooser(send, null))
        }) { Text(stringResource(R.string.autotune_share)) }
        TextButton(onClick = onClear) { Text(stringResource(R.string.autotune_clear)) }
    }
}

/** The answer to "what should I do": one headline and counts, from the hourly suggestions. Advice only: nothing is changed. */
@Composable
private fun ActionSummary(a: AutotuneAdvice, previous: PreviousRun?) {
    val rows = a.hours.map { h ->
        val sug = AutotuneAdvisor.roundToPumpStep(h.suggested)
        h to (if (h.current > 0) (sug / h.current - 1) * 100 else 0.0)
    }
    val raised = rows.count { it.second >= 10 }
    val lowered = rows.count { it.second <= -10 }
    val held = a.hours.count { it.heldReason != null }
    val lowConf = a.hours.count { it.confidence == app.bganalyzer.domain.Confidence.LOW }
    val biggest = rows.filter { it.first.heldReason == null }.maxByOrNull { kotlin.math.abs(it.second) }
    val tooEarly = a.daysTuned < 5
    val headline = when {
        tooEarly -> stringResource(R.string.autotune_sum_early, a.daysTuned)
        raised + lowered == 0 && held == 0 -> stringResource(R.string.autotune_sum_fine)
        biggest != null && kotlin.math.abs(biggest.second) >= 10 -> stringResource(R.string.autotune_sum_change, hourLabel(biggest.first.hour), String.format(Locale.getDefault(), "%+.0f%%", biggest.second))
        else -> stringResource(R.string.autotune_sum_held_only)
    }
    SectionCard(stringResource(R.string.autotune_sum_title)) {
        Text(headline, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
        TileRow {
            StatTile(raised.toString(), stringResource(R.string.autotune_sum_raised))
            StatTile(lowered.toString(), stringResource(R.string.autotune_sum_lowered))
        }
        TileRow {
            StatTile(held.toString(), stringResource(R.string.autotune_sum_held))
            StatTile(lowConf.toString(), stringResource(R.string.autotune_sum_low_conf))
        }
        if (previous != null) {
            val moved = a.hours.count { kotlin.math.abs(AutotuneAdvisor.roundToPumpStep(it.suggested) - previous.rates[it.hour]) >= 0.1 }
            val whenText = java.text.DateFormat.getDateInstance(java.text.DateFormat.MEDIUM).format(java.util.Date(previous.atMs))
            Text(stringResource(if (moved == 0) R.string.autotune_stable else R.string.autotune_moved, whenText, moved), style = MaterialTheme.typography.bodyMedium)
        }
        Text(stringResource(R.string.autotune_responsibility), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** The suggestions as plain text a person can paste into notes or send to a care team. */
private fun shareText(a: AutotuneAdvice, unit: GlucoseUnit): String = buildString {
    appendLine("BGAnalyzer Autotune suggestion (advice only, not applied anywhere)")
    appendLine("Days used: ${a.daysTuned}")
    appendLine("Insulin sensitivity ${unit.label}/U: now ${unit.format(a.currentIsf)}, suggested ${unit.format(a.tunedIsf)}")
    appendLine("Carb ratio g/U: now ${String.format(Locale.US, "%.1f", a.currentCarbRatio)}, suggested ${String.format(Locale.US, "%.1f", a.tunedCarbRatio)}")
    appendLine()
    appendLine("Hour  Now  Suggested  Confidence")
    a.hours.forEach { h ->
        appendLine("${hourLabel(h.hour)}  ${String.format(Locale.US, "%.2f", h.current)}  ${String.format(Locale.US, "%.2f", AutotuneAdvisor.roundToPumpStep(h.suggested))}  ${h.confidence.name.lowercase()}")
    }
    appendLine()
    append("Check any change with your diabetes care team before using it.")
}
