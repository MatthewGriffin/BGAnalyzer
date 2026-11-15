package app.bganalyzer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.bganalyzer.R
import app.bganalyzer.domain.BlockStats
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.domain.MealBlockStats
import app.bganalyzer.domain.PostMeal
import app.bganalyzer.domain.TimeBlocks
import app.bganalyzer.domain.format
import java.util.Locale

private val PERIODS = listOf(7, 14, 30, 60, 90)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PatternsScreen(state: PatternsState, unit: GlucoseUnit, onDays: (Int) -> Unit, onBlockHours: (Int) -> Unit) {
    Scaffold(topBar = { TopAppBar(title = { Text(stringResource(R.string.patterns_title)) }) }) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(stringResource(R.string.patterns_intro))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Dropdown(
                    label = stringResource(R.string.range_label),
                    options = PERIODS,
                    selected = state.days,
                    text = { stringResource(R.string.range_days, it) },
                    onSelect = onDays,
                    modifier = Modifier.weight(1f),
                )
                Dropdown(
                    label = stringResource(R.string.patterns_block_label),
                    options = TimeBlocks.ALLOWED_BLOCK_HOURS,
                    selected = state.blockHours,
                    text = { stringResource(R.string.patterns_block_hours, it) },
                    onSelect = onBlockHours,
                    modifier = Modifier.weight(1f),
                )
            }
            if (state.loaded && state.readingCount == 0) {
                Text(stringResource(R.string.patterns_no_data))
                return@Column
            }
            if (state.zoneName.isNotEmpty()) Text(stringResource(R.string.patterns_timezone, state.zoneName), style = MaterialTheme.typography.bodySmall)
            Text(stringResource(R.string.patterns_glucose_title), style = MaterialTheme.typography.titleMedium)
            state.blocks.forEach { BlockCard(it, unit) }
            Text(stringResource(R.string.patterns_meals_title), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(R.string.patterns_meals_intro), style = MaterialTheme.typography.bodySmall)
            state.meals.forEach { MealCard(it, unit) }
        }
    }
}

private fun hour(h: Int) = String.format(Locale.US, "%02d:00", h % 24)
private fun pct(v: Double) = String.format(Locale.getDefault(), "%.0f", v)

@Composable
private fun BlockCard(b: BlockStats, unit: GlucoseUnit) {
    val tir = b.timeInRange
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.patterns_block_time, hour(b.startHour), hour(b.endHour)), style = MaterialTheme.typography.titleSmall)
            if (!b.enoughDays) {
                Text(stringResource(R.string.patterns_not_enough, b.days, TimeBlocks.MIN_DAYS))
                return@Column
            }
            Text(stringResource(R.string.patterns_days, b.days), style = MaterialTheme.typography.bodySmall)
            Text(stringResource(R.string.patterns_in_range, pct(tir.inRangePct)))
            Text(stringResource(R.string.patterns_below, pct(tir.lowPct + tir.veryLowPct)))
            Text(stringResource(R.string.patterns_above, pct(tir.highPct + tir.veryHighPct)))
            Text(stringResource(R.string.patterns_average, unit.format(tir.meanMgdl), unit.label))
            if (b.lowDays > 0) Text(stringResource(R.string.patterns_low_days, b.lowDays, b.days), color = MaterialTheme.colorScheme.error)
            if (b.veryLowDays > 0) Text(stringResource(R.string.patterns_very_low_days, b.veryLowDays, b.days), color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun MealCard(m: MealBlockStats, unit: GlucoseUnit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.patterns_block_time, hour(m.startHour), hour(m.endHour)), style = MaterialTheme.typography.titleSmall)
            if (m.meals == 0) {
                Text(stringResource(R.string.patterns_meals_count, 0))
                return@Column
            }
            if (!m.enoughMeals) {
                Text(stringResource(R.string.patterns_meals_not_enough, m.meals, PostMeal.MIN_MEALS))
                return@Column
            }
            Text(stringResource(R.string.patterns_meals_count, m.meals), style = MaterialTheme.typography.bodySmall)
            // A rise is a difference, so it converts without an offset.
            Text(stringResource(R.string.patterns_meal_rise, unit.format(m.medianRiseMgdl), unit.label))
            m.medianAt2hMgdl?.let { Text(stringResource(R.string.patterns_meal_2h, unit.format(it), unit.label)) }
            if (m.withReading2h > 0) Text(stringResource(R.string.patterns_meal_high2h, m.highAt2h, m.withReading2h))
            Text(
                stringResource(R.string.patterns_meal_low4h, m.lowWithin4h, m.meals),
                color = if (m.lowWithin4h > 0) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}
