package app.bganalyzer.ui

import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * The frame every tab shares: a title bar and a scrolling column with the same padding and spacing. The scroll position is
 * saved, so it survives switching tabs (see the saveable state in MainActivity) and rotating the phone.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ScreenScaffold(title: String, onRefresh: (() -> Unit)? = null, refreshing: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    val scroll = rememberSaveable(saver = ScrollState.Saver) { ScrollState(0) }
    // The bottom bar and the status bar are handled by the activity and the title bar, so no extra insets here.
    Scaffold(contentWindowInsets = WindowInsets(0, 0, 0, 0), topBar = { TopAppBar(title = { Text(title) }) }) { padding ->
        val column: @Composable () -> Unit = {
            Column(
                Modifier.fillMaxSize().padding(16.dp).verticalScroll(scroll),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                content = content,
            )
        }
        if (onRefresh == null) Box(Modifier.padding(padding)) { column() }
        else androidx.compose.material3.pulltorefresh.PullToRefreshBox(isRefreshing = refreshing, onRefresh = onRefresh, modifier = Modifier.padding(padding)) { column() }
    }
}
