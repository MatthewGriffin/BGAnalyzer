package app.bganalyzer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.bganalyzer.R
import app.bganalyzer.mongo.ConnectionReport
import java.text.DateFormat
import java.util.Date

/** The Nightscout REST source's fields and callbacks. [source] is `mongo` or `rest`. */
data class RestUi(
    val source: String = "mongo",
    val url: String = "",
    /** `none`, `token` or `secret`. */
    val auth: String = "none",
    val secret: String = "",
    val onSource: (String) -> Unit = {},
    val onUrl: (String) -> Unit = {},
    val onAuth: (String) -> Unit = {},
    val onSecret: (String) -> Unit = {},
    val onTest: () -> Unit = {},
)

sealed interface TestState {
    data object Idle : TestState
    data object Running : TestState
    data class Ok(val report: ConnectionReport) : TestState
    data class Failed(val message: String) : TestState
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConnectionScreen(
    uri: String,
    database: String,
    testState: TestState,
    storedReadingCount: Int,
    onUriChange: (String) -> Unit,
    onDatabaseChange: (String) -> Unit,
    onTest: () -> Unit,
    rest: RestUi = RestUi(),
) {
    Scaffold(contentWindowInsets = androidx.compose.foundation.layout.WindowInsets(0, 0, 0, 0), topBar = { TopAppBar(title = { Text(stringResource(R.string.connection_title)) }) }) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(stringResource(R.string.connection_intro))
            Dropdown(
                label = stringResource(R.string.source_label),
                options = listOf("mongo", "rest"),
                selected = rest.source,
                text = { stringResource(if (it == "rest") R.string.source_rest else R.string.source_mongo) },
                onSelect = rest.onSource,
                modifier = Modifier.fillMaxWidth(),
            )
            if (rest.source == "rest") {
                Text(stringResource(R.string.rest_intro), style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(
                    value = rest.url, onValueChange = rest.onUrl,
                    label = { Text(stringResource(R.string.rest_url_label)) },
                    placeholder = { Text(stringResource(R.string.rest_url_placeholder)) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false),
                    modifier = Modifier.fillMaxWidth(),
                )
                Dropdown(
                    label = stringResource(R.string.rest_auth_label),
                    options = listOf("none", "token", "secret"),
                    selected = rest.auth,
                    text = { stringResource(when (it) { "token" -> R.string.rest_auth_token; "secret" -> R.string.rest_auth_secret; else -> R.string.rest_auth_none }) },
                    onSelect = rest.onAuth,
                    modifier = Modifier.fillMaxWidth(),
                )
                if (rest.auth != "none") {
                    OutlinedTextField(
                        value = rest.secret, onValueChange = rest.onSecret,
                        label = { Text(stringResource(if (rest.auth == "token") R.string.rest_token_label else R.string.rest_secret_label)) },
                        singleLine = true,
                        visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                Button(onClick = rest.onTest, enabled = testState != TestState.Running && rest.url.isNotBlank() && (rest.auth == "none" || rest.secret.isNotBlank())) {
                    Text(stringResource(if (testState == TestState.Running) R.string.connection_testing else R.string.connection_test_button))
                }
            } else {
            OutlinedTextField(
                value = uri,
                onValueChange = onUriChange,
                label = { Text(stringResource(R.string.connection_uri_label)) },
                placeholder = { Text(stringResource(R.string.connection_uri_placeholder)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = database,
                onValueChange = onDatabaseChange,
                label = { Text(stringResource(R.string.connection_database_label)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(autoCorrectEnabled = false),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = onTest,
                enabled = testState != TestState.Running && uri.isNotBlank() && database.isNotBlank(),
            ) {
                Text(stringResource(if (testState == TestState.Running) R.string.connection_testing else R.string.connection_test_button))
            }
            }
            when (testState) {
                is TestState.Ok -> {
                    val report = testState.report
                    Text(stringResource(R.string.connection_ok_title, report.database), style = MaterialTheme.typography.titleMedium)
                    report.collectionCounts.forEach { (name, count) ->
                        Text(stringResource(R.string.connection_ok_count, name, count))
                    }
                    val newest = report.newestEntryMs
                    if (newest == null) {
                        Text(stringResource(R.string.connection_ok_no_entries), color = MaterialTheme.colorScheme.error)
                    } else {
                        val time = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(newest))
                        Text(stringResource(R.string.connection_ok_newest, time))
                    }
                }
                is TestState.Failed -> {
                    Text(
                        stringResource(R.string.connection_failed_title),
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.error,
                    )
                    Text(testState.message)
                }
                TestState.Idle, TestState.Running -> Unit
            }
            Text(
                stringResource(R.string.connection_stored_count, storedReadingCount),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Preview
@Composable
private fun ConnectionScreenPreview() {
    BGAnalyzerTheme {
        ConnectionScreen(
            uri = "",
            database = "nightscout",
            testState = TestState.Ok(ConnectionReport("nightscout", mapOf("entries" to 57000L, "treatments" to 6500L), 1_790_000_000_000L)),
            storedReadingCount = 0,
            onUriChange = {},
            onDatabaseChange = {},
            onTest = {},
        )
    }
}
