package app.bganalyzer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.bganalyzer.R
import app.bganalyzer.data.ExcludedDayEntity

/** Days to leave out of Autotune (and of the Patterns tab): suggested days with no insulin records, and a manual picker. */
@Composable
internal fun ExcludedDaysCards(
    days: Int,
    excludedDays: List<ExcludedDayEntity>,
    noInsulinDays: List<String>,
    onExclude: (String, String) -> Unit,
    onRestore: (String) -> Unit,
    onExcludeDays: (List<String>, String) -> Unit,
) {
    NoInsulinDaysCard(noInsulinDays, onExcludeDays)
    ExcludedDaysSection(days, excludedDays, onExclude, onRestore)
}

@Composable
private fun NoInsulinDaysCard(noInsulinDays: List<String>, onExcludeDays: (List<String>, String) -> Unit) {
    if (noInsulinDays.isNotEmpty()) {
        val noInsulinNote = stringResource(R.string.no_insulin_note)
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(stringResource(R.string.no_insulin_title, noInsulinDays.size), style = MaterialTheme.typography.titleSmall)
                Text(stringResource(R.string.no_insulin_intro), style = MaterialTheme.typography.bodySmall)
                Text(noInsulinDays.joinToString(", "), style = MaterialTheme.typography.bodySmall)
                androidx.compose.material3.Button(onClick = { onExcludeDays(noInsulinDays, noInsulinNote) }) {
                    Text(stringResource(R.string.no_insulin_button))
                }
            }
        }
    }
}

/** Mark days as bad data, e.g. a pump failure with insulin pens in use. Excluded days are left out of Autotune and of Patterns. */
@Composable
private fun ExcludedDaysSection(days: Int, excludedDays: List<ExcludedDayEntity>, onExclude: (String, String) -> Unit, onRestore: (String) -> Unit) {
    val already = excludedDays.map { it.date }.toSet()
    val candidates = (0 until days).map { java.time.LocalDate.now().minusDays(it.toLong()).toString() }.filter { it !in already }
    var picked by androidx.compose.runtime.remember(candidates.firstOrNull()) { androidx.compose.runtime.mutableStateOf(candidates.firstOrNull()) }
    var note by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf("") }
    val defaultNote = stringResource(R.string.excluded_default_note)
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
                androidx.compose.material3.Button(onClick = { onExclude(picked ?: candidates.first(), note.ifBlank { defaultNote }); note = "" }) {
                    Text(stringResource(R.string.excluded_button))
                }
            }
            excludedDays.forEach { d ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    Text("${d.date}  ${d.note}", Modifier.weight(1f))
                    androidx.compose.material3.TextButton(onClick = { onRestore(d.date) }) { Text(stringResource(R.string.excluded_restore)) }
                }
            }
        }
    }
}

