package app.bganalyzer.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.bganalyzer.domain.GlucoseRanges
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.format
import java.text.DateFormat
import java.util.Date

/** Readings further apart than this are drawn as a gap, not joined by a line. */
private const val GAP_MS = 20 * 60 * 1000L

@Composable
fun GlucoseChart(
    points: List<ChartPoint>,
    fromMs: Long,
    toMs: Long,
    unit: GlucoseUnit,
    ranges: GlucoseRanges = GlucoseRanges(),
    modifier: Modifier = Modifier,
) {
    val measurer = rememberTextMeasurer()
    val labelStyle = TextStyle(fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    val line = MaterialTheme.colorScheme.primary
    val band = Color(0xFF2E9E5B).copy(alpha = 0.15f)
    val grid = MaterialTheme.colorScheme.outlineVariant
    val danger = MaterialTheme.colorScheme.error.copy(alpha = 0.6f)
    val dateFormat = DateFormat.getDateInstance(DateFormat.SHORT)
    val timeFormat = DateFormat.getTimeInstance(DateFormat.SHORT)
    val oneDay = toMs - fromMs <= 24 * 60 * 60 * 1000L + 1

    Canvas(modifier.fillMaxWidth().height(240.dp)) {
        val left = 36.dp.toPx()
        val bottom = 20.dp.toPx()
        val w = size.width - left
        val h = size.height - bottom
        val top = 0f
        val yMax = maxOf(300.0, points.maxOfOrNull { it.mgdl } ?: 0.0).let { Math.ceil(it / 50) * 50 }
        val yMin = 40.0
        fun x(t: Long) = left + w * ((t - fromMs).toFloat() / (toMs - fromMs).toFloat())
        fun y(v: Double) = top + h * (1f - ((v - yMin) / (yMax - yMin)).toFloat())

        drawRect(band, Offset(left, y(ranges.highAbove)), Size(w, y(ranges.lowBelow) - y(ranges.highAbove)))
        listOf(ranges.veryLowBelow, ranges.veryHighAbove).forEach {
            if (it in yMin..yMax) drawLine(danger, Offset(left, y(it)), Offset(left + w, y(it)), 1.dp.toPx())
        }
        listOf(ranges.lowBelow, ranges.highAbove).forEach {
            drawLine(grid, Offset(left, y(it)), Offset(left + w, y(it)), 1.dp.toPx())
            val label = unit.format(it)
            val m = measurer.measure(label, labelStyle)
            drawText(m, topLeft = Offset(left - m.size.width - 4.dp.toPx(), y(it) - m.size.height / 2f))
        }
        val xLabelY = top + h + 4.dp.toPx()
        listOf(fromMs to 0f, toMs to 1f).forEach { (t, anchor) ->
            val label = if (oneDay) timeFormat.format(Date(t)) else dateFormat.format(Date(t))
            val m = measurer.measure(label, labelStyle)
            drawText(m, topLeft = Offset(left + (w - m.size.width) * anchor, xLabelY))
        }

        val path = Path()
        var prev: ChartPoint? = null
        val dots = ArrayList<Offset>()
        for (p in points) {
            val px = x(p.timeMs)
            val py = y(p.mgdl.coerceIn(yMin, yMax))
            if (prev == null || p.timeMs - prev.timeMs > GAP_MS) {
                path.moveTo(px, py)
                dots.add(Offset(px, py))
            } else path.lineTo(px, py)
            prev = p
        }
        drawPath(path, line, style = Stroke(width = 1.5.dp.toPx()))
        // A lone reading between gaps has no line, so mark each segment start with a dot.
        dots.forEach { drawCircle(line, 1.5.dp.toPx(), it) }
    }
}
