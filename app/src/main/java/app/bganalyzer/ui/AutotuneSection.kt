package app.bganalyzer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.bganalyzer.R
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.format
import java.util.Locale

private val AUTOTUNE_DAYS = listOf(5, 7, 14, 21, 30)

/** Autotune (ported from AndroidAPS) as advice only: nothing is changed in any profile. */
@Composable
fun AutotuneSection(state: AutotuneState, unit: GlucoseUnit, peak: Int, onPeak: (Int) -> Unit, onRun: (Int) -> Unit, onClear: () -> Unit) {
    var days by remember { mutableIntStateOf(14) }
    Text(stringResource(R.string.autotune_title), style = MaterialTheme.typography.titleMedium)
    Text(stringResource(R.string.autotune_intro), style = MaterialTheme.typography.bodySmall)
    Dropdown(
        label = stringResource(R.string.autotune_days_label),
        options = AUTOTUNE_DAYS,
        selected = days,
        text = { stringResource(R.string.range_days, it) },
        onSelect = { days = it },
        modifier = Modifier.fillMaxWidth(),
    )
    Dropdown(
        label = stringResource(R.string.autotune_insulin_label),
        options = AutotuneViewModel.INSULIN_PEAKS,
        selected = peak,
        text = { stringResource(when (it) { 55 -> R.string.autotune_insulin_ultra; 45 -> R.string.autotune_insulin_lyumjev; else -> R.string.autotune_insulin_rapid }) },
        onSelect = onPeak,
        modifier = Modifier.fillMaxWidth(),
    )
    Button(onClick = { onRun(days) }, enabled = state !is AutotuneState.Running) { Text(stringResource(R.string.autotune_run)) }
    when (state) {
        AutotuneState.Idle -> Unit
        is AutotuneState.Running -> Text(stringResource(R.string.autotune_running, state.day, state.of))
        is AutotuneState.Failed -> Text(state.message, color = MaterialTheme.colorScheme.error)
        is AutotuneState.Done -> AutotuneResultCards(state, unit, onClear)
    }
}

private fun rate(v: Double) = String.format(Locale.getDefault(), "%.2f", v)

@Composable
private fun AutotuneResultCards(s: AutotuneState.Done, unit: GlucoseUnit, onClear: () -> Unit) {
    val a = s.advice
    Text(stringResource(R.string.autotune_days_used, a.daysTuned, s.days), style = MaterialTheme.typography.bodySmall)
    if (s.result.skipped.isNotEmpty()) {
        Text(stringResource(R.string.autotune_skipped, s.result.skipped.joinToString { "${it.date} (${it.reason})" }), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary)
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.autotune_isf_cr), style = MaterialTheme.typography.titleSmall)
            Text(stringResource(R.string.autotune_isf, unit.format(a.currentIsf), unit.format(a.tunedIsf), unit.label))
            Text(stringResource(R.string.autotune_cr, rate(a.currentCarbRatio), rate(a.tunedCarbRatio)))
            Text(stringResource(R.string.autotune_isf_cr_note), style = MaterialTheme.typography.bodySmall)
            val lowCr = a.mealsUsed < app.bganalyzer.autotune.AutotuneAdvisor.MIN_MEALS
            val lowIsf = a.isfPoints < app.bganalyzer.autotune.AutotuneAdvisor.MIN_ISF_POINTS
            Text(
                stringResource(R.string.autotune_evidence, a.mealsUsed, a.isfPoints) + if (lowCr || lowIsf) " " + stringResource(R.string.autotune_evidence_low) else "",
                style = MaterialTheme.typography.bodySmall, color = if (lowCr || lowIsf) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            )
        }
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(stringResource(R.string.autotune_basal), style = MaterialTheme.typography.titleSmall)
            a.hours.forEach { h ->
                val change = if (h.current > 0) (h.suggested / h.current - 1) * 100 else 0.0
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(String.format(Locale.US, "%02d:00", h.hour))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("${rate(h.current)} -> ${rate(h.suggested)} U/h (${String.format(Locale.getDefault(), "%+.0f", change)}%)")
                        Text(h.confidence.name.lowercase(), color = confidenceColor(h.confidence), fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                    }
                }
                h.heldReason?.let { Text(stringResource(R.string.autotune_held, rate(h.tuned), it), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
            }
            Text(stringResource(R.string.autotune_basal_note), style = MaterialTheme.typography.bodySmall)
        }
    }
    TextButton(onClick = onClear) { Text(stringResource(R.string.autotune_clear)) }
}
