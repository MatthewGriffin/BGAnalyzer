package app.bganalyzer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.bganalyzer.R
import app.bganalyzer.domain.GlucoseUnit

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(readingCount: Int, displayUnit: GlucoseUnit) {
    Scaffold(topBar = { TopAppBar(title = { Text(stringResource(R.string.app_name)) }) }) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (readingCount == 0) {
                Text(stringResource(R.string.home_no_data_title), style = MaterialTheme.typography.titleLarge)
                Text(stringResource(R.string.home_no_data_body, displayUnit.label))
            } else {
                Text(stringResource(R.string.home_reading_count, readingCount))
            }
        }
    }
}

@Preview
@Composable
private fun HomeScreenPreview() {
    BGAnalyzerTheme { HomeScreen(readingCount = 0, displayUnit = GlucoseUnit.MMOL) }
}
