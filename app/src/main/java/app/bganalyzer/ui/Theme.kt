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

/** Green, amber and red for high, medium and low confidence. Fixed colours (not the dynamic scheme) so they always read the same. */
@Composable
fun confidenceColor(confidence: app.bganalyzer.domain.Confidence): androidx.compose.ui.graphics.Color {
    val dark = isSystemInDarkTheme()
    return when (confidence) {
        app.bganalyzer.domain.Confidence.HIGH -> if (dark) androidx.compose.ui.graphics.Color(0xFF81C784) else androidx.compose.ui.graphics.Color(0xFF2E7D32)
        app.bganalyzer.domain.Confidence.MEDIUM -> if (dark) androidx.compose.ui.graphics.Color(0xFFFFB74D) else androidx.compose.ui.graphics.Color(0xFFB26A00)
        app.bganalyzer.domain.Confidence.LOW -> if (dark) androidx.compose.ui.graphics.Color(0xFFE57373) else androidx.compose.ui.graphics.Color(0xFFC62828)
    }
}

/** Where a glucose value sits against the target range. */
enum class GlucoseBand { IN_RANGE, HIGH, VERY_HIGH, LOW, VERY_LOW }

/** One colour code for glucose everywhere: in range green, high orange, low red (darker for very high and very low). */
@Composable
fun glucoseColor(band: GlucoseBand): androidx.compose.ui.graphics.Color {
    val dark = isSystemInDarkTheme()
    fun c(light: Long, darkTheme: Long) = androidx.compose.ui.graphics.Color(if (dark) darkTheme else light)
    return when (band) {
        GlucoseBand.IN_RANGE -> c(0xFF2E9E5B, 0xFF6FCF97)
        GlucoseBand.HIGH -> c(0xFFE8780A, 0xFFFFA040)
        GlucoseBand.VERY_HIGH -> c(0xFFC25A00, 0xFFFF8A3D)
        GlucoseBand.LOW -> c(0xFFD64545, 0xFFFF7B7B)
        GlucoseBand.VERY_LOW -> c(0xFF9B1C1C, 0xFFE05252)
    }
}
