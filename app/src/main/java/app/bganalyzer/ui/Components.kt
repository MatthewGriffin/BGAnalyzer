package app.bganalyzer.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.bganalyzer.domain.TimeInRange
import java.util.Locale

/** The card every section uses: a title, then content with even spacing. A null title gives a card with no heading. */
@Composable
internal fun SectionCard(title: String?, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Card(
        modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (title != null) Text(title, style = MaterialTheme.typography.titleMedium)
            content()
        }
    }
}

/** A small caption above a group inside a card. */
@Composable
internal fun GroupLabel(text: String) {
    Text(text.uppercase(), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 4.dp))
}

/** A big number with a small caption under it. Tiles in a [TileRow] share the width. */
@Composable
internal fun RowScope.StatTile(value: String, caption: String, valueColor: Color = MaterialTheme.colorScheme.onSurface) {
    Column(
        Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).background(MaterialTheme.colorScheme.surfaceContainerHighest).padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, color = valueColor)
        Text(caption, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
internal fun TileRow(content: @Composable RowScope.() -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), content = content)
}

/** One label on the left and its value on the right, for lists of facts. */
@Composable
internal fun FactRow(label: String, value: String, valueColor: Color = MaterialTheme.colorScheme.onSurface) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f).padding(end = 12.dp))
        Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, color = valueColor)
    }
}

/** A coloured dot, used for confidence so a column of them reads at a glance. */
@Composable
internal fun Dot(color: Color, size: Int = 10) {
    Box(Modifier.size(size.dp).clip(CircleShape).background(color))
}

/** Time in range as one bar split into very low, low, in range, high and very high, in glucose colours. */
@Composable
internal fun RangeBar(tir: TimeInRange, modifier: Modifier = Modifier) {
    val parts = listOf(
        tir.veryLowPct to glucoseColor(GlucoseBand.VERY_LOW),
        tir.lowPct to glucoseColor(GlucoseBand.LOW),
        tir.inRangePct to glucoseColor(GlucoseBand.IN_RANGE),
        tir.highPct to glucoseColor(GlucoseBand.HIGH),
        tir.veryHighPct to glucoseColor(GlucoseBand.VERY_HIGH),
    ).filter { it.first > 0.0 }
    Row(modifier.fillMaxWidth().height(14.dp).clip(RoundedCornerShape(7.dp)).background(MaterialTheme.colorScheme.surfaceContainerHighest)) {
        parts.forEach { (pct, colour) -> Box(Modifier.weight(pct.toFloat()).height(14.dp).background(colour)) }
    }
}

/** A coloured percentage with its label, for the legend under a [RangeBar]. */
@Composable
internal fun RowScope.RangeLegend(label: String, pct: Double, color: Color) {
    Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Dot(color, 8)
        Column {
            Text(String.format(Locale.getDefault(), "%.0f%%", pct), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/**
 * Two stepped lines over 24 hours, the profile now and the suggestion, so a day's whole shape can be compared at a glance.
 * Hours are the values at 00:00 to 23:00; each is held for its hour.
 */
@Composable
internal fun BasalStepChart(now: List<Double>, suggested: List<Double>, modifier: Modifier = Modifier) {
    if (now.size != 24 || suggested.size != 24) return
    val nowColor = MaterialTheme.colorScheme.outline
    val sugColor = MaterialTheme.colorScheme.primary
    val grid = MaterialTheme.colorScheme.outlineVariant
    val top = (now + suggested).max().coerceAtLeast(0.1) * 1.1
    Canvas(modifier.fillMaxWidth().height(110.dp)) {
        val w = size.width; val h = size.height
        fun x(hour: Int) = w * hour / 24f
        fun y(v: Double) = (h - (v / top * h)).toFloat()
        for (g in listOf(0, 6, 12, 18, 24)) drawLine(grid, Offset(x(g), 0f), Offset(x(g), h), strokeWidth = 1f)
        fun line(values: List<Double>, colour: Color, width: Float) {
            val p = Path()
            values.forEachIndexed { i, v ->
                if (i == 0) p.moveTo(x(0), y(v)) else p.lineTo(x(i), y(v))
                p.lineTo(x(i + 1), y(v))
            }
            drawPath(p, colour, style = Stroke(width = width))
        }
        line(now, nowColor, 3f)
        line(suggested, sugColor, 5f)
    }
}
