package app.bganalyzer.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

@Composable
fun BGAnalyzerTheme(content: @Composable () -> Unit) {
    // minSdk is 30 and dynamic colour needs 31, so older phones get the default Material scheme.
    val context = LocalContext.current
    val dark = isSystemInDarkTheme()
    val colors = when {
        android.os.Build.VERSION.SDK_INT < 31 ->
            if (dark) androidx.compose.material3.darkColorScheme() else androidx.compose.material3.lightColorScheme()
        dark -> dynamicDarkColorScheme(context)
        else -> dynamicLightColorScheme(context)
    }
    MaterialTheme(colorScheme = colors, content = content)
}
