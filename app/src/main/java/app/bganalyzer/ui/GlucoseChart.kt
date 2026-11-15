package app.bganalyzer.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.bganalyzer.R
import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.IobSampleEntity
import app.bganalyzer.domain.BasalSegment
import app.bganalyzer.domain.GlucoseRanges
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.Moment
import app.bganalyzer.domain.format
import java.text.DateFormat
import java.util.Date
import java.util.Locale

/** Readings further apart than this are drawn as a gap, not joined by a line. */
private const val GAP_MS = 20 * 60 * 1000L
private val AXIS_WIDTH = 40.dp
private val BASAL_COLOR = Color(0xFF1F9E8F)
private val BOLUS_COLOR = Color(0xFF3B6FD4)
private val SMB_COLOR = Color(0xFF8DB0F0)
private val CARB_COLOR = Color(0xFFE08A1E)
private val IOB_COLOR = Color(0xFF8E4FD0)
/** IOB samples further apart than this are drawn as a gap. */
private const val IOB_GAP_MS = 60 * 60 * 1000L

/**
 * The glucose chart, the insulin panel under it, and a readout for the moment the user touches.
 * Touching or sliding a finger across either chart moves a vertical line through both and fills the readout.
 */
@Composable
fun GlucoseCharts(state: GlucoseUiState, ranges: GlucoseRanges = GlucoseRanges()) {
    var selected by remember(state.days) { mutableStateOf<Long?>(null) }
    val axisPx = with(LocalDensity.current) { AXIS_WIDTH.toPx() }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Column(
            Modifier.pointerInput(state.fromMs, state.toMs) {
                fun at(x: Float) = state.fromMs + ((x - axisPx) / (size.width - axisPx)).coerceIn(0f, 1f) * (state.toMs - state.fromMs)
                detectTapGestures { selected = at(it.x).toLong() }
            }.pointerInput(state.fromMs, state.toMs) {
                fun at(x: Float) = state.fromMs + ((x - axisPx) / (size.width - axisPx)).coerceIn(0f, 1f) * (state.toMs - state.fromMs)
                // Horizontal only, so swiping up or down over the chart still scrolls the page.
                detectHorizontalDragGestures(
                    onDragStart = { selected = at(it.x).toLong() },
                    onHorizontalDrag = { change, _ -> change.consume(); selected = at(change.position.x).toLong() },
                )
            },
        ) {
            val overlaid = state.layout == ChartLayout.OVERLAID
            GlucoseChart(state.points, state.fromMs, state.toMs, state.unit, state.treatments, state.basal, state.iob, overlaid, selected, ranges)
            if (!overlaid) InsulinPanel(state, selected)
        }
        // With nothing touched the card describes right now (the end of the chart).
        val moment = Moment.at(selected ?: (state.toMs - 1), state.points, state.treatments, state.basal, state.iob)
        MomentCard(
            moment, state.unit, isNow = selected == null, latest = state.points.lastOrNull(),
            onBackToNow = { selected = null },
        )
        if (selected == null) Text(stringResource(R.string.chart_touch_hint), style = MaterialTheme.typography.bodySmall)
        Text(
            stringResource(if (state.layout == ChartLayout.OVERLAID) R.string.chart_legend_overlaid else R.string.chart_legend) +
                if (state.layout == ChartLayout.OVERLAID && state.iob.isNotEmpty()) " " + stringResource(R.string.chart_legend_iob) else "",
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun MomentCard(
    m: app.bganalyzer.domain.MomentSummary,
    unit: GlucoseUnit,
    isNow: Boolean,
    latest: GlucoseReadingEntity?,
    onBackToNow: () -> Unit,
) {
    val fmt = remember { DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT) }
    fun ago(ms: Long): String {
        val min = ms / 60_000
        return if (min < 60) "$min min" else "${min / 60} h ${min % 60} min"
    }
    fun one(v: Double) = String.format(Locale.getDefault(), "%.1f", v)
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(
                if (isNow) stringResource(R.string.moment_now, fmt.format(Date(m.timeMs))) else fmt.format(Date(m.timeMs)),
                style = MaterialTheme.typography.titleSmall,
            )
            val glucose = m.mgdl
            Text(
                when {
                    glucose != null -> stringResource(R.string.moment_glucose, unit.format(glucose), unit.label)
                    // Right now but the newest reading is old (not synced lately): say so rather than show nothing.
                    isNow && latest != null -> stringResource(
                        R.string.moment_latest_reading, unit.format(latest.mgdl), unit.label, ago(m.timeMs - latest.timestampMs),
                    )
                    else -> stringResource(R.string.moment_no_reading)
                },
            )
            val basal = m.basal
            Text(
                if (basal == null) stringResource(R.string.moment_no_basal)
                else stringResource(
                    if (basal.scheduled) R.string.moment_basal_scheduled else R.string.moment_basal_temp,
                    String.format(Locale.getDefault(), "%.2f", basal.rateUph),
                ),
            )
            val iobSample = m.iob
            Text(
                when {
                    iobSample?.iob != null && iobSample.basalIob != null -> stringResource(R.string.moment_iob, String.format(Locale.getDefault(), "%.2f", iobSample.iob), String.format(Locale.getDefault(), "%.2f", iobSample.basalIob))
                    iobSample?.iob != null -> stringResource(R.string.moment_iob_only, String.format(Locale.getDefault(), "%.2f", iobSample.iob))
                    else -> stringResource(R.string.moment_no_iob)
                },
            )
            iobSample?.cob?.takeIf { it > 0 }?.let { Text(stringResource(R.string.moment_cob, one(it))) }
            Text(stringResource(R.string.moment_last3h, one(m.carbsLast3h), one(m.bolusLast3h)))
            m.lastCarbs?.let { Text(stringResource(R.string.moment_last_carbs, one(it.first), ago(it.second))) }
            m.lastBolus?.let {
                Text(stringResource(if (it.second) R.string.moment_last_smb else R.string.moment_last_bolus, String.format(Locale.getDefault(), "%.2f", it.first), ago(it.third)))
            }
            if (!isNow) TextButton(onClick = onBackToNow) { Text(stringResource(R.string.moment_back_to_now)) }
        }
    }
}

@Composable
fun GlucoseChart(
    points: List<GlucoseReadingEntity>,
    fromMs: Long,
    toMs: Long,
    unit: GlucoseUnit,
    treatments: List<app.bganalyzer.data.TreatmentEntity>,
    basal: List<BasalSegment>,
    iob: List<IobSampleEntity>,
    /** True: basal and markers are drawn on the glucose chart itself, like AAPS. False: only carb dots; insulin has its own panel. */
    overlay: Boolean,
    selectedMs: Long?,
    ranges: GlucoseRanges = GlucoseRanges(),
    modifier: Modifier = Modifier,
) {
    val measurer = rememberTextMeasurer()
    val labelStyle = TextStyle(fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    val line = MaterialTheme.colorScheme.primary
    val basalLabel = TextStyle(fontSize = 11.sp, color = BASAL_COLOR)
    val markerLabel = TextStyle(fontSize = 10.sp, color = MaterialTheme.colorScheme.onSurface)
    val band = Color(0xFF2E9E5B).copy(alpha = 0.15f)
    val grid = MaterialTheme.colorScheme.outlineVariant
    val danger = MaterialTheme.colorScheme.error.copy(alpha = 0.6f)
    val cursor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
    val dateFormat = DateFormat.getDateInstance(DateFormat.SHORT)
    // A 24-hour window starts and ends at the same clock time, so include the date.
    val timeFormat = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT)
    val oneDay = toMs - fromMs <= 24 * 60 * 60 * 1000L + 1

    Canvas(modifier.fillMaxWidth().height(if (overlay) 300.dp else 220.dp)) {
        val left = AXIS_WIDTH.toPx()
        val bottom = 20.dp.toPx()
        val w = size.width - left
        val h = size.height - bottom
        val yMax = maxOf(300.0, points.maxOfOrNull { it.mgdl } ?: 0.0).let { Math.ceil(it / 50) * 50 }
        val yMin = 40.0
        fun x(t: Long) = left + w * ((t - fromMs).toFloat() / (toMs - fromMs).toFloat())
        fun y(v: Double) = h * (1f - ((v - yMin) / (yMax - yMin)).toFloat())

        drawRect(band, Offset(left, y(ranges.highAbove)), Size(w, y(ranges.lowBelow) - y(ranges.highAbove)))
        if (overlay) {
            // Basal as a translucent step area along the bottom, on its own scale (labelled at the top of the area).
            val basalMax = (basal.maxOfOrNull { it.rateUph } ?: 0.0).coerceAtLeast(0.5).let { Math.ceil(it * 2) / 2 }
            val zone = h * 0.28f
            for (s in basal) {
                val top = h - zone * (s.rateUph / basalMax).toFloat().coerceIn(0f, 1f)
                drawRect(BASAL_COLOR.copy(alpha = if (s.scheduled) 0.15f else 0.32f), Offset(x(s.startMs), top), Size((x(s.endMs) - x(s.startMs)).coerceAtLeast(0.5f), h - top))
                drawLine(BASAL_COLOR.copy(alpha = if (s.scheduled) 0.5f else 0.9f), Offset(x(s.startMs), top), Offset(x(s.endMs), top), 1.2.dp.toPx())
            }
            val m = measurer.measure(String.format(Locale.getDefault(), "%.1f U/h", basalMax), basalLabel)
            drawText(m, topLeft = Offset(left - m.size.width - 4.dp.toPx(), h - zone - m.size.height / 2f))
        }
        listOf(ranges.veryLowBelow, ranges.veryHighAbove).forEach {
            if (it in yMin..yMax) drawLine(danger, Offset(left, y(it)), Offset(left + w, y(it)), 1.dp.toPx())
        }
        listOf(ranges.lowBelow, ranges.highAbove).forEach {
            drawLine(grid, Offset(left, y(it)), Offset(left + w, y(it)), 1.dp.toPx())
            val m = measurer.measure(unit.format(it), labelStyle)
            drawText(m, topLeft = Offset(left - m.size.width - 4.dp.toPx(), y(it) - m.size.height / 2f))
        }
        val xLabelY = h + 4.dp.toPx()
        listOf(fromMs to 0f, toMs to 1f).forEach { (t, anchor) ->
            val label = if (oneDay) timeFormat.format(Date(t)) else dateFormat.format(Date(t))
            val m = measurer.measure(label, labelStyle)
            drawText(m, topLeft = Offset(left + (w - m.size.width) * anchor, xLabelY))
        }

        if (!overlay) {
            // Carbs as dots along the bottom edge, for periods up to 14 days where they stay readable.
            if (toMs - fromMs <= 14L * 24 * 60 * 60 * 1000) {
                for (t in treatments) if ((t.carbs ?: 0.0) > 0 && t.timestampMs in fromMs..toMs) {
                    drawCircle(CARB_COLOR, 3.dp.toPx(), Offset(x(t.timestampMs), h - 4.dp.toPx()))
                }
            }
        }

        val path = Path()
        var prev: GlucoseReadingEntity? = null
        val dots = ArrayList<Offset>()
        var lastX = Float.NEGATIVE_INFINITY
        for (p in points) {
            val px = x(p.timestampMs)
            val py = y(p.mgdl.coerceIn(yMin, yMax))
            if (prev == null || p.timestampMs - prev.timestampMs > GAP_MS) {
                path.moveTo(px, py); dots.add(Offset(px, py)); lastX = px
            } else if (px - lastX >= 1f) {
                // Long periods hold far more readings than pixels, so draw at most one point per pixel column.
                path.lineTo(px, py); lastX = px
            }
            prev = p
        }
        drawPath(path, line, style = Stroke(width = 1.5.dp.toPx()))
        dots.forEach { drawCircle(line, 1.5.dp.toPx(), it) }
        if (overlay && iob.isNotEmpty()) {
            // Insulin on board as a purple line on its own scale: 0 at the bottom, the highest value at 45% of the height.
            val iobMax = Math.ceil((iob.maxOfOrNull { it.iob ?: 0.0 } ?: 0.0).coerceAtLeast(1.0))
            val zone = h * 0.45f
            val iobPath = Path()
            var prevT = Long.MIN_VALUE
            var lastIobX = Float.NEGATIVE_INFINITY
            for (smp in iob) {
                val v = smp.iob ?: continue
                if (smp.timestampMs !in fromMs..toMs) continue
                val px = x(smp.timestampMs)
                val py = h - zone * (v / iobMax).toFloat().coerceIn(0f, 1f)
                if (prevT == Long.MIN_VALUE || smp.timestampMs - prevT > IOB_GAP_MS) { iobPath.moveTo(px, py); lastIobX = px }
                else if (px - lastIobX >= 1f) { iobPath.lineTo(px, py); lastIobX = px }
                prevT = smp.timestampMs
            }
            drawPath(iobPath, IOB_COLOR, style = Stroke(width = 1.5.dp.toPx()))
            val m = measurer.measure(String.format(Locale.getDefault(), "%.0f U IOB", iobMax), TextStyle(fontSize = 11.sp, color = IOB_COLOR))
            drawText(m, topLeft = Offset(left + w - m.size.width - 4.dp.toPx(), h - zone - m.size.height))
        }
        if (overlay) {
            // Carbs (orange circle) and boluses (blue triangle) sit on the glucose line at the time they happened.
            // Amounts are written next to them only when the period is short enough to stay readable.
            val labels = toMs - fromMs <= 2L * 24 * 60 * 60 * 1000
            for (t in treatments) {
                if (t.timestampMs !in fromMs..toMs) continue
                val px = x(t.timestampMs)
                val gy = Moment.glucoseNear(points, t.timestampMs)?.let { y(it.coerceIn(yMin, yMax)) } ?: (h * 0.5f)
                val carbs = t.carbs ?: 0.0
                val insulin = t.insulin ?: 0.0
                if (carbs > 0) {
                    val c = Offset(px, (gy - 12.dp.toPx()).coerceAtLeast(6.dp.toPx()))
                    drawCircle(CARB_COLOR, 4.dp.toPx(), c)
                    if (labels) {
                        val m = measurer.measure(String.format(Locale.getDefault(), "%.0fg", carbs), TextStyle(fontSize = 10.sp, color = CARB_COLOR))
                        drawText(m, topLeft = Offset((c.x - m.size.width / 2f).coerceIn(left, size.width - m.size.width), c.y - 6.dp.toPx() - m.size.height))
                    }
                }
                if (insulin > 0) {
                    val tri = if (t.isSmb) 3.dp.toPx() else 5.5.dp.toPx()
                    val cy = (gy + 12.dp.toPx()).coerceAtMost(h - 6.dp.toPx())
                    val shape = Path().apply {
                        moveTo(px, cy - tri); lineTo(px - tri, cy + tri * 0.7f); lineTo(px + tri, cy + tri * 0.7f); close()
                    }
                    drawPath(shape, if (t.isSmb) SMB_COLOR else BOLUS_COLOR)
                    if (labels && !t.isSmb) {
                        val m = measurer.measure(String.format(Locale.getDefault(), "%.1fU", insulin), TextStyle(fontSize = 10.sp, color = BOLUS_COLOR))
                        drawText(m, topLeft = Offset((px - m.size.width / 2f).coerceIn(left, size.width - m.size.width), (cy + tri).coerceAtMost(h - m.size.height)))
                    }
                }
            }
        }
        drawCursor(selectedMs, ::x, cursor, 0f, h, fromMs, toMs)
    }
}

private fun DrawScope.drawCursor(selected: Long?, x: (Long) -> Float, color: Color, top: Float, bottom: Float, fromMs: Long, toMs: Long) {
    if (selected == null || selected < fromMs || selected > toMs) return
    drawLine(color, Offset(x(selected), top), Offset(x(selected), bottom), 1.5.dp.toPx())
}

/**
 * Basal as a step area (teal; lighter where it comes from the profile schedule) and insulin boluses as bars
 * (blue; lighter for automatic micro-boluses). It has its own scale, so small boluses are easy to read:
 * the tallest bar and the highest basal rate each reach near the top.
 */
@Composable
private fun InsulinPanel(state: GlucoseUiState, selectedMs: Long?) {
    val measurer = rememberTextMeasurer()
    val basalLabel = TextStyle(fontSize = 11.sp, color = BASAL_COLOR)
    val bolusLabel = TextStyle(fontSize = 11.sp, color = BOLUS_COLOR)
    val grid = MaterialTheme.colorScheme.outlineVariant
    val cursor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
    val fromMs = state.fromMs
    val toMs = state.toMs
    val boluses = state.treatments.filter { (it.insulin ?: 0.0) > 0 }

    Canvas(Modifier.fillMaxWidth().height(130.dp)) {
        val left = AXIS_WIDTH.toPx()
        val w = size.width - left
        val h = size.height - 4.dp.toPx()
        // Round the scales up to tidy numbers so the labels read cleanly.
        val basalMax = (state.basal.maxOfOrNull { it.rateUph } ?: 0.0).coerceAtLeast(0.5).let { Math.ceil(it * 2) / 2 }
        val bolusMax = (boluses.maxOfOrNull { it.insulin!! } ?: 0.0).coerceAtLeast(1.0).let { Math.ceil(it) }
        fun x(t: Long) = left + w * ((t - fromMs).toFloat() / (toMs - fromMs).toFloat())

        drawLine(grid, Offset(left, h), Offset(left + w, h), 1.dp.toPx())
        drawLine(grid, Offset(left, 0f), Offset(left + w, 0f), 1.dp.toPx())

        for (s in state.basal) {
            val top = h - h * (s.rateUph / basalMax).toFloat().coerceIn(0f, 1f)
            val a = if (s.scheduled) 0.18f else 0.40f
            drawRect(BASAL_COLOR.copy(alpha = a), Offset(x(s.startMs), top), Size((x(s.endMs) - x(s.startMs)).coerceAtLeast(0.5f), h - top))
            drawLine(BASAL_COLOR.copy(alpha = if (s.scheduled) 0.5f else 1f), Offset(x(s.startMs), top), Offset(x(s.endMs), top), 1.5.dp.toPx())
        }
        val barWidth = (if (toMs - fromMs <= 3L * 24 * 3600 * 1000) 4.dp else 2.dp).toPx()
        for (t in boluses) {
            if (t.timestampMs !in fromMs..toMs) continue
            val barH = h * (t.insulin!! / bolusMax).toFloat().coerceIn(0f, 1f)
            drawRect(if (t.isSmb) SMB_COLOR else BOLUS_COLOR, Offset(x(t.timestampMs) - barWidth / 2, h - barH), Size(barWidth, barH))
        }

        // Axis labels: the basal scale in teal on the left, the bolus scale in blue just inside it.
        fun label(text: String, style: TextStyle, yPos: Float, rightAligned: Boolean) {
            val m = measurer.measure(text, style)
            drawText(m, topLeft = Offset(if (rightAligned) left - m.size.width - 4.dp.toPx() else left + 4.dp.toPx(), yPos))
        }
        label(String.format(Locale.getDefault(), "%.1f U/h", basalMax), basalLabel, 0f, true)
        label("0", basalLabel, h - 14.dp.toPx(), true)
        label(String.format(Locale.getDefault(), "%.0f U", bolusMax), bolusLabel, 0f, false)
        drawCursor(selectedMs, ::x, cursor, 0f, h, fromMs, toMs)
    }
}
