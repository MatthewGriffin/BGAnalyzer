package app.bganalyzer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.mongo.ConnectionErrors
import app.bganalyzer.mongo.NightscoutMongo
import app.bganalyzer.settings.ConnectionStore
import app.bganalyzer.ui.BGAnalyzerTheme
import app.bganalyzer.ui.ConnectionScreen
import app.bganalyzer.ui.TestState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val readingCount = AppDatabase.get(this).glucoseReadingDao().observeCount()
        val store = ConnectionStore(this)
        setContent {
            BGAnalyzerTheme {
                val count by readingCount.collectAsState(initial = 0)
                var uri by remember { mutableStateOf(store.uri) }
                var database by remember { mutableStateOf(store.database) }
                var followAddress by remember { mutableStateOf(store.database.isBlank()) }
                var testState by remember { mutableStateOf<TestState>(TestState.Idle) }
                val scope = rememberCoroutineScope()
                ConnectionScreen(
                    uri = uri,
                    database = database,
                    testState = testState,
                    storedReadingCount = count,
                    onUriChange = { newUri ->
                        uri = newUri
                        // Follow the database named in the address until the user types a name themselves.
                        if (followAddress) database = NightscoutMongo.databaseInUri(newUri) ?: ""
                    },
                    onDatabaseChange = {
                        followAddress = false
                        database = it
                    },
                    onTest = {
                        testState = TestState.Running
                        scope.launch {
                            testState = withContext(Dispatchers.IO) {
                                try {
                                    val report = NightscoutMongo.test(uri, database.trim())
                                    // Only an address that worked is kept.
                                    store.uri = uri.trim()
                                    store.database = database.trim()
                                    TestState.Ok(report)
                                } catch (e: Exception) {
                                    TestState.Failed(ConnectionErrors.describe(e))
                                }
                            }
                        }
                    },
                )
            }
        }
    }
}
