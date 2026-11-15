package app.bganalyzer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import app.bganalyzer.ui.BackupScreen
import app.bganalyzer.ui.BackupViewModel
import app.bganalyzer.ui.GlucoseScreen
import app.bganalyzer.ui.PatternsScreen
import app.bganalyzer.ui.PatternsViewModel
import app.bganalyzer.ui.AutotuneScreen
import app.bganalyzer.ui.AutotuneViewModel
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
import app.bganalyzer.rest.RestAuth
import app.bganalyzer.rest.RestSyncSource
import app.bganalyzer.settings.ConnectionStore
import app.bganalyzer.settings.RestStore
import app.bganalyzer.ui.RestUi
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
    private val autotune: AutotuneViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val readingCount = AppDatabase.get(this).glucoseReadingDao().observeCount()
        val store = ConnectionStore(this)
        val restStore = RestStore(this)
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
                var restSource by remember(restores) { mutableStateOf(restStore.source) }
                var restUrl by remember(restores) { mutableStateOf(restStore.url) }
                var restAuth by remember(restores) { mutableStateOf(restStore.authType) }
                var restSecret by remember(restores) { mutableStateOf(restStore.secret) }
                val scope = rememberCoroutineScope()
                var tab by rememberSaveable { mutableStateOf(0) }
                val glucoseState by glucose.state.collectAsState()
                val syncState by glucose.sync.collectAsState()
                Scaffold(
                    // The screens' own top bars handle the status bar; the bottom bar handles the navigation bar.
                    contentWindowInsets = WindowInsets(0, 0, 0, 0),
                    bottomBar = {
                        NavigationBar {
                            listOf(R.string.tab_glucose, R.string.tab_autotune, R.string.tab_patterns, R.string.tab_connection, R.string.tab_backup).forEachIndexed { i, label ->
                                NavigationBarItem(
                                    selected = tab == i,
                                    onClick = {
                                        tab = i
                                        if (i == 0) glucose.refreshWindow()
                                        // Autotune and Patterns work on the saved data, so bring the last period up to date first.
                                        if (i == 1) glucose.syncIfStale(30)
                                        if (i == 2) { patterns.refresh(); glucose.syncIfStale(patterns.state.value.days) }
                                    },
                                    icon = {},
                                    // one line even at a large font size: five tabs share the width
                                    label = { Text(stringResource(label), maxLines = 1, softWrap = false, style = androidx.compose.material3.MaterialTheme.typography.labelSmall) },
                                    alwaysShowLabel = true,
                                )
                            }
                        }
                    },
                ) { inner ->
                // Each tab keeps its saved state (scroll position, typed text) while another tab is shown.
                val tabState = rememberSaveableStateHolder()
                tabState.SaveableStateProvider(tab) {
                if (tab == 0) {
                    Box(Modifier.padding(inner)) {
                        GlucoseScreen(
                            state = glucoseState,
                            sync = syncState,
                            hasConnection = glucose.hasConnection,
                            onDaysChange = glucose::setDays,
                            onUnitChange = glucose::setUnit,
                            onLayoutChange = glucose::setLayout,
                            onSync = { glucose.sync(glucoseState.days) },
                        )
                    }
                } else if (tab == 1) {
                    val autotuneState by autotune.state.collectAsState()
                    val insulinPeak by autotune.peak.collectAsState()
                    val autotuneDays by autotune.days.collectAsState()
                    Box(Modifier.padding(inner)) {
                        AutotuneScreen(autotuneState, glucoseState.unit, autotuneDays, autotune::setDays, insulinPeak, syncState, autotune::setPeak, autotune::run, autotune::clear)
                    }
                } else if (tab == 2) {
                    val patternsState by patterns.state.collectAsState()
                    Box(Modifier.padding(inner)) {
                        PatternsScreen(
                            patternsState, glucoseState.unit, syncState, glucose.hasConnection,
                            patterns::setDays, patterns::setBlockHours, onSync = { glucose.sync(patternsState.days) },
                            onExcludeDay = patterns::excludeDay, onRestoreDay = patterns::restoreDay, onExcludeDays = patterns::excludeDays,
                        )
                    }
                } else if (tab == 4) {
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
                    rest = RestUi(
                        source = restSource, url = restUrl, auth = restAuth, secret = restSecret,
                        // Choosing a source only switches which one a sync reads; nothing saved is changed or removed.
                        onSource = { restSource = it; restStore.source = it; testState = TestState.Idle },
                        onUrl = { restUrl = it },
                        onAuth = { restAuth = it },
                        onSecret = { restSecret = it },
                        onTest = {
                            testState = TestState.Running
                            scope.launch {
                                testState = withContext(Dispatchers.IO) {
                                    try {
                                        val auth = when (restAuth) {
                                            RestStore.AUTH_TOKEN -> RestAuth.Token(restSecret.trim())
                                            RestStore.AUTH_SECRET -> RestAuth.ApiSecret(restSecret.trim())
                                            else -> RestAuth.None
                                        }
                                        val report = RestSyncSource(restUrl, auth).test()
                                        // Only settings that worked are kept.
                                        restStore.url = RestSyncSource.normalizeUrl(restUrl)
                                        restStore.authType = restAuth
                                        restStore.secret = if (restAuth == RestStore.AUTH_NONE) "" else restSecret.trim()
                                        restUrl = restStore.url
                                        TestState.Ok(report)
                                    } catch (e: Exception) {
                                        TestState.Failed(ConnectionErrors.describe(e))
                                    }
                                }
                            }
                        },
                    ),
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
}
