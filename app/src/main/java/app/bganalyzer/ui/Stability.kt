package app.bganalyzer.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import app.bganalyzer.R
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.PeriodSummary
import app.bganalyzer.domain.format
import java.util.Locale

/** How steady glucose was: the average rate of change (0 is a flat line) and the coefficient of variation. */
@Composable
internal fun StabilityLine(swingMgdlPerHour: Double?, cvPct: Double, unit: GlucoseUnit, modifier: androidx.compose.ui.Modifier = androidx.compose.ui.Modifier) {
    if (swingMgdlPerHour == null) return
    Text(
        stringResource(R.string.stability_line, unit.format(swingMgdlPerHour), unit.label, String.format(Locale.getDefault(), "%.0f", cvPct)),
        style = MaterialTheme.typography.bodyMedium, modifier = modifier,
    )
}

/** Compares the swing before and after a change. Lower is steadier. Not coloured like glucose, so it is never read as high or low. */
@Composable
internal fun StabilityVerdict(before: PeriodSummary, after: PeriodSummary) {
    val b = before.swingMgdlPerHour ?: return
    val a = after.swingMgdlPerHour ?: return
    if (b <= 0.0) return
    val change = (a / b - 1) * 100
    val (text, colour) = when {
        change <= -10 -> stringResource(R.string.stability_steadier, String.format(Locale.getDefault(), "%.0f", -change)) to MaterialTheme.colorScheme.primary
        change >= 10 -> stringResource(R.string.stability_less_steady, String.format(Locale.getDefault(), "%.0f", change)) to MaterialTheme.colorScheme.tertiary
        else -> stringResource(R.string.stability_same) to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Text(text, style = MaterialTheme.typography.bodyMedium, color = colour)
}
