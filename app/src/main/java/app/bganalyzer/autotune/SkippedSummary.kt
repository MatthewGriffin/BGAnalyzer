package app.bganalyzer.autotune

import java.time.LocalDate

/** Skipped days as short lines: consecutive days with the same reason become one range. */
object SkippedSummary {
    /** One line per run of consecutive days with the same reason, e.g. "2026-11-01 to 2026-11-11: no insulin records". */
    fun lines(skipped: List<SkippedDay>): List<String> {
        val out = ArrayList<String>()
        var i = 0
        val sorted = skipped.sortedBy { it.date }
        while (i < sorted.size) {
            var j = i
            while (j + 1 < sorted.size && sorted[j + 1].reason == sorted[i].reason &&
                LocalDate.parse(sorted[j + 1].date) == LocalDate.parse(sorted[j].date).plusDays(1)) j++
            out += if (j == i) "${sorted[i].date}: ${sorted[i].reason}" else "${sorted[i].date} to ${sorted[j].date}: ${sorted[i].reason}"
            i = j + 1
        }
        return out
    }

    fun text(skipped: List<SkippedDay>) = lines(skipped).joinToString("; ")
}
