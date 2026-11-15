package app.bganalyzer.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.res.stringResource
import app.bganalyzer.R

/** Says which days Nightscout returned nothing for, so missing data can be told apart from data the app failed to fetch. */
@Composable
fun EmptyDaysNotice(ranges: List<app.bganalyzer.sync.EmptyRange>) {
    if (ranges.isEmpty()) return
    val fmt = remember { java.text.DateFormat.getDateInstance(java.text.DateFormat.SHORT) }
    fun day(d: java.time.LocalDate) = fmt.format(java.util.Date.from(d.atStartOfDay(java.time.ZoneId.systemDefault()).toInstant()))
    Text(stringResource(R.string.empty_days_title), style = MaterialTheme.typography.titleSmall)
    ranges.groupBy { it.source }.forEach { (source, list) ->
        val label = stringResource(
            when (source) {
                app.bganalyzer.sync.Sources.TREATMENTS -> R.string.empty_days_treatments
                app.bganalyzer.sync.Sources.IOB -> R.string.empty_days_iob
                else -> R.string.empty_days_glucose
            },
        )
        val text = list.joinToString(", ") { if (it.from == it.to) day(it.from) else day(it.from) + " – " + day(it.to) }
        Text(stringResource(R.string.empty_days_line, label, text), style = MaterialTheme.typography.bodyMedium)
    }
}
