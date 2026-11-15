package app.bganalyzer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.domain.GlucoseUnit
import app.bganalyzer.ui.BGAnalyzerTheme
import app.bganalyzer.ui.HomeScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val readingCount = AppDatabase.get(this).glucoseReadingDao().observeCount()
        setContent {
            BGAnalyzerTheme {
                val count by readingCount.collectAsState(initial = 0)
                // The display unit becomes a setting once there is a settings screen.
                HomeScreen(readingCount = count, displayUnit = GlucoseUnit.MMOL)
            }
        }
    }
}
