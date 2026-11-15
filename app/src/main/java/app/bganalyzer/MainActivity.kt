package app.bganalyzer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import app.bganalyzer.ui.BackupScreen
import app.bganalyzer.ui.BackupViewModel
import app.bganalyzer.ui.GlucoseScreen
import app.bganalyzer.ui.PatternsScreen
import app.bganalyzer.ui.PatternsViewModel
import app.bganalyzer.ui.GlucoseViewModel
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
    private val glucose: GlucoseViewModel by viewModels()
    private val backup: BackupViewModel by viewModels()
    private val patterns: PatternsViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val readingCount = AppDatabase.get(this).glucoseReadingDao().observeCount()
        val store = ConnectionStore(this)
        setContent {
            BGAnalyzerTheme {
                val count by readingCount.collectAsState(initial = 0)
                val restores by backup.restoreCount.collectAsState()
                val backupState by backup.state.collectAsState()
                // After a restore, reload the connection fields from storage instead of keeping stale text.
                var uri by remember(restores) { mutableStateOf(store.uri) }
                var database by remember(restores) { mutableStateOf(store.database) }
                var followAddress by remember(restores) { mutableStateOf(store.database.isBlank()) }
                var testState by remember { mutableStateOf<TestState>(TestState.Idle) }
                val scope = rememberCoroutineScope()
                var tab by rememberSaveable { mutableStateOf(0) }
                val glucoseState by glucose.state.collectAsState()
                val syncState by glucose.sync.collectAsState()
                Scaffold(
                    bottomBar = {
                        NavigationBar {
                            listOf(R.string.tab_glucose, R.string.tab_patterns, R.string.tab_connection, R.string.tab_backup).forEachIndexed { i, label ->
                                NavigationBarItem(
                                    selected = tab == i,
                                    onClick = { tab = i; if (i == 0) glucose.refreshWindow(); if (i == 1) patterns.refresh() },
                                    icon = {},
                                    label = { Text(stringResource(label)) },
                                    alwaysShowLabel = true,
                                )
                            }
                        }
                    },
                ) { inner ->
                if (tab == 0) {
                    Box(Modifier.padding(inner)) {
                        GlucoseScreen(
                            state = glucoseState,
                            sync = syncState,
                            hasConnection = glucose.hasConnection,
                            onDaysChange = glucose::setDays,
                            onUnitChange = glucose::setUnit,
                            onSync = glucose::sync,
                        )
                    }
                } else if (tab == 1) {
                    val patternsState by patterns.state.collectAsState()
                    Box(Modifier.padding(inner)) {
                        PatternsScreen(patternsState, glucoseState.unit, patterns::setDays, patterns::setBlockHours)
                    }
                } else if (tab == 3) {
                    Box(Modifier.padding(inner)) {
                        BackupScreen(backupState, onSave = backup::save, onRestore = backup::restore)
                    }
                } else Box(Modifier.padding(inner)) {
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
    }
}
