package app.bganalyzer.sync

/** A stretch of time meaning "records after [startMs] up to and including [endMs]". */
data class Span(val startMs: Long, val endMs: Long) {
    init { require(endMs >= startMs) { "span ends before it starts" } }
    val lengthMs get() = endMs - startMs
}

object Intervals {
    /** Sorts spans and joins any that overlap, touch, or sit within [joinWithinMs] of each other. Empty spans are dropped. */
    fun merge(spans: List<Span>, joinWithinMs: Long = 0): List<Span> {
        val out = ArrayList<Span>()
        for (s in spans.filter { it.endMs > it.startMs }.sortedBy { it.startMs }) {
            val last = out.lastOrNull()
            if (last != null && s.startMs <= last.endMs + joinWithinMs) out[out.size - 1] = last.copy(endMs = maxOf(last.endMs, s.endMs))
            else out.add(s)
        }
        return out
    }

    /** The parts of [whole] that [covered] does not cover. */
    fun subtract(whole: Span, covered: List<Span>): List<Span> {
        val out = ArrayList<Span>()
        var cursor = whole.startMs
        for (c in merge(covered)) {
            if (c.endMs <= cursor) continue
            if (c.startMs >= whole.endMs) break
            if (c.startMs > cursor) out.add(Span(cursor, minOf(c.startMs, whole.endMs)))
            cursor = maxOf(cursor, c.endMs)
            if (cursor >= whole.endMs) break
        }
        if (cursor < whole.endMs) out.add(Span(cursor, whole.endMs))
        return out
    }

    /** The part of [span] inside [whole], or null if none. */
    fun clamp(span: Span, whole: Span): Span? {
        val s = maxOf(span.startMs, whole.startMs); val e = minOf(span.endMs, whole.endMs)
        return if (e > s) Span(s, e) else null
    }
}
