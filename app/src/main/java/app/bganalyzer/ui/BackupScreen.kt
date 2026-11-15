package app.bganalyzer.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import app.bganalyzer.R
import app.bganalyzer.backup.BackupCodec
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BackupScreen(state: BackupState, onSave: (android.net.Uri, String) -> Unit, onRestore: (android.net.Uri, String) -> Unit) {
    var passphrase by rememberSaveable { mutableStateOf("") }
    val saveLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) {
        if (it != null) onSave(it, passphrase)
    }
    val restoreLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) {
        if (it != null) onRestore(it, passphrase)
    }
    val valid = passphrase.length >= BackupCodec.MIN_PASSPHRASE_LENGTH
    val busy = state == BackupState.Working
    Scaffold(topBar = { TopAppBar(title = { Text(stringResource(R.string.backup_title)) }) }) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(stringResource(R.string.backup_intro))
            OutlinedTextField(
                value = passphrase,
                onValueChange = { passphrase = it },
                label = { Text(stringResource(R.string.backup_passphrase_label)) },
                supportingText = { Text(stringResource(R.string.backup_passphrase_hint, BackupCodec.MIN_PASSPHRASE_LENGTH)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text, autoCorrectEnabled = false),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = { saveLauncher.launch("bganalyzer-${SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())}.bgbackup") },
                enabled = valid && !busy,
            ) { Text(stringResource(R.string.backup_save)) }
            OutlinedButton(onClick = { restoreLauncher.launch(arrayOf("*/*")) }, enabled = valid && !busy) {
                Text(stringResource(R.string.backup_restore))
            }
            when (state) {
                BackupState.Working -> Text(stringResource(R.string.backup_working))
                is BackupState.Saved -> Text(stringResource(R.string.backup_saved, state.readings))
                is BackupState.Restored -> {
                    Text(stringResource(R.string.backup_restored, state.readings))
                    Text(stringResource(if (state.connectionRestored) R.string.backup_restored_connection else R.string.backup_restored_no_connection))
                }
                is BackupState.Failed -> {
                    Text(stringResource(R.string.backup_failed), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.titleSmall)
                    Text(state.message)
                }
                BackupState.Idle -> Unit
            }
        }
    }
}
