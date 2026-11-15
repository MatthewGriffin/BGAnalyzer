package app.bganalyzer.ui

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.bganalyzer.R
import app.bganalyzer.backup.AppBackup
import app.bganalyzer.backup.BackupException
import app.bganalyzer.data.AppDatabase
import app.bganalyzer.settings.ConnectionStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

sealed interface BackupState {
    data object Idle : BackupState
    data object Working : BackupState
    data class Saved(val readings: Int) : BackupState
    data class Restored(val readings: Int, val connectionRestored: Boolean) : BackupState
    data class Failed(val message: String) : BackupState
}

class BackupViewModel(private val app: Application) : AndroidViewModel(app) {
    private val backup = AppBackup(AppDatabase.get(app).let { it.glucoseReadingDao() }, AppDatabase.get(app).treatmentDao(), AppDatabase.get(app).profileDao(), AppDatabase.get(app).iobDao(), ConnectionStore(app))
    private val _state = MutableStateFlow<BackupState>(BackupState.Idle)
    val state: StateFlow<BackupState> = _state

    /** Bumped after a restore so screens that copied the saved connection into their own state reload it. */
    private val _restoreCount = MutableStateFlow(0)
    val restoreCount: StateFlow<Int> = _restoreCount

    fun save(uri: Uri, passphrase: String) = launch {
        // "wt" so a shorter backup replaces an existing longer file instead of leaving old bytes behind.
        val out = app.contentResolver.openOutputStream(uri, "wt") ?: error("Could not open the file for writing.")
        val count = out.use { backup.export(it, passphrase) }
        BackupState.Saved(count)
    }

    fun restore(uri: Uri, passphrase: String) = launch {
        val input = app.contentResolver.openInputStream(uri) ?: error("Could not open the file.")
        val result = input.use { backup.restore(it, passphrase) }
        _restoreCount.value += 1
        BackupState.Restored(result.readings, result.connectionRestored)
    }

    private fun launch(block: suspend () -> BackupState) {
        if (_state.value == BackupState.Working) return
        _state.value = BackupState.Working
        viewModelScope.launch(Dispatchers.IO) {
            _state.value = try {
                block()
            } catch (e: BackupException) {
                BackupState.Failed(e.message ?: app.getString(R.string.backup_failed))
            } catch (e: Exception) {
                BackupState.Failed(e.message ?: app.getString(R.string.backup_failed))
            }
        }
    }
}
