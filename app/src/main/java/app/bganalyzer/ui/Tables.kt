package app.bganalyzer.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/** One table row: cells share the width by weight, and a rule is drawn under it. */
@Composable
internal fun TableRow(cells: List<String>, weights: List<Float>, header: Boolean = false, colours: List<androidx.compose.ui.graphics.Color?> = emptyList(), note: String? = null, boldColumn: Int = 2) {
    Column(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            cells.forEachIndexed { i, text ->
                Text(
                    text, Modifier.weight(weights[i]),
                    textAlign = if (i == 0) TextAlign.Start else TextAlign.End,
                    fontWeight = if (header || i == boldColumn) FontWeight.Bold else FontWeight.Normal,
                    style = if (header) MaterialTheme.typography.labelMedium else MaterialTheme.typography.bodyMedium,
                    color = colours.getOrNull(i) ?: MaterialTheme.colorScheme.onSurface,
                )
            }
        }
        note?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(bottom = 6.dp)) }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

