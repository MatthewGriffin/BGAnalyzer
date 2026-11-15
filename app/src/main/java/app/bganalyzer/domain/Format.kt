package app.bganalyzer.domain

import java.util.Locale

/** Formats a mg/dL value in the display unit: whole numbers for mg/dL, one decimal for mmol/L. */
fun GlucoseUnit.format(mgdl: Double): String =
    if (this == GlucoseUnit.MGDL) String.format(Locale.getDefault(), "%.0f", mgdl)
    else String.format(Locale.getDefault(), "%.1f", fromMgdl(mgdl))

/** Share of expected readings present, assuming one reading every five minutes, capped at 100. */
fun coveragePercent(readingCount: Int, periodMs: Long): Int {
    val expected = periodMs / (5 * 60 * 1000.0)
    return if (expected <= 0) 0 else minOf(100.0, 100.0 * readingCount / expected).toInt()
}
