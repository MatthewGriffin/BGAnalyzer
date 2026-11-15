package app.bganalyzer.rest

import app.bganalyzer.mongo.ConnectionReport
import app.bganalyzer.sync.DocCursor
import app.bganalyzer.sync.ListCursor
import app.bganalyzer.sync.Span
import app.bganalyzer.sync.SyncPlanner
import app.bganalyzer.sync.SyncSource
import org.bson.Document
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.zip.GZIPInputStream

/** How the app proves itself to Nightscout. A public (read-only) site needs none. */
sealed interface RestAuth {
    data object None : RestAuth
    /** A Nightscout access token (Admin tools, Subjects), sent as `?token=`. */
    data class Token(val value: String) : RestAuth
    /** The site's API_SECRET, sent as its SHA-1 hash in the `api-secret` header. */
    data class ApiSecret(val value: String) : RestAuth
}

/** A failed REST request, in words that never contain the token or secret. */
class RestException(message: String) : Exception(message)

/** One GET. Replaced by a fake in tests. Returns the body text or throws [RestException]. */
fun interface HttpGet { fun get(url: String, headers: Map<String, String>): String }

/** The real HTTP call: HTTPS only (Android blocks plain HTTP), with timeouts, gzip accepted. */
object UrlConnectionGet : HttpGet {
    override fun get(url: String, headers: Map<String, String>): String {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = 20_000
            conn.readTimeout = 60_000
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("Accept-Encoding", "gzip")
            conn.setRequestProperty("User-Agent", "BGAnalyzer")
            headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
            val code = conn.responseCode
            if (code == 401 || code == 403) throw RestException("Nightscout refused access (HTTP $code). Check the token or API secret.")
            if (code == 404) throw RestException("Nightscout answered 'not found' (HTTP 404). Check the address.")
            if (code !in 200..299) throw RestException("Nightscout answered HTTP $code.")
            val stream = if (conn.contentEncoding?.equals("gzip", true) == true) GZIPInputStream(conn.inputStream) else conn.inputStream
            return stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } catch (e: RestException) {
            throw e
        } catch (e: java.io.IOException) {
            throw RestException("Could not reach Nightscout: ${e.javaClass.simpleName}${e.message?.let { ": " + it.replace(Regex("https?://\\S+"), "(address hidden)") } ?: ""}")
        } finally {
            conn.disconnect()
        }
    }
}

/**
 * Reads Nightscout over its REST API (v1) with small time windows, so there is no request-size limit or slow giant query:
 * a window that comes back full is split in half and asked again. Works with the same planning as the MongoDB source.
 */
class RestSyncSource(baseUrl: String, private val auth: RestAuth, private val http: HttpGet = UrlConnectionGet) : SyncSource {
    private val base = normalizeUrl(baseUrl)

    // --- SyncSource ---

    override fun glucose(spans: List<Span>): DocCursor = cursor {
        for (span in spans) yieldAll(windowed(span, GLUCOSE_WINDOW_MS) { w ->
            fetch("entries/sgv.json", dateRange("date", w.startMs, w.endMs))
        })
    }

    override fun treatments(spans: List<Span>, editedAfterMs: Long?): DocCursor = cursor {
        val seen = HashSet<Any?>()
        for (span in spans) {
            yieldAll(windowed(span, TREATMENT_WINDOW_MS) { w -> fetch("treatments.json", isoRange("created_at", w)) }.filter { seen.add(it["_id"]) })
            yieldAll(windowed(span, TREATMENT_WINDOW_MS) { w -> fetch("treatments.json", dateRange("date", w.startMs, w.endMs)) }.filter { seen.add(it["_id"]) })
        }
        if (editedAfterMs != null) {
            yieldAll(fetch("treatments.json", listOf("find[srvModified][\$gt]" to editedAfterMs.toString())).filter { seen.add(it["_id"]) })
        }
    }

    override fun profileEventsBefore(beforeMs: Long): DocCursor = cursor {
        val before = "find[date][\$lte]" to beforeMs.toString()
        yieldAll(fetch("treatments.json", listOf("find[eventType]" to "Profile Switch", before), count = 6))
        yieldAll(fetch("treatments.json", listOf("find[eventType]" to "Note", "find[profileJson][\$exists]" to "true", before), count = 6))
    }

    override fun iob(spans: List<Span>): DocCursor = cursor {
        val seen = HashSet<Any?>()
        val loopOnly = "find[openaps.iob][\$exists]" to "true"
        for (span in spans) {
            yieldAll(windowed(span, IOB_WINDOW_MS) { w -> fetch("devicestatus.json", listOf(loopOnly) + isoRange("created_at", w)) }.filter { seen.add(it["_id"]) })
            yieldAll(windowed(span, IOB_WINDOW_MS) { w -> fetch("devicestatus.json", listOf(loopOnly) + dateRange("date", w.startMs, w.endMs)) }.filter { seen.add(it["_id"]) })
        }
    }

    override fun profiles(newestStartMs: Long?): DocCursor = cursor {
        // The profile endpoint ignores `find`, so ask for the newest ones and keep those that are new.
        val cutoff = newestStartMs?.let { SyncPlanner.iso(it - SyncPlanner.DAY_MS) }
        yieldAll(fetch("profile.json", emptyList(), count = MAX_PROFILES).filter { cutoff == null || (it["created_at"] as? String ?: "") > cutoff })
    }

    override fun close() {}

    // --- connection test ---

    /** Reads the server status and the newest glucose entry, and checks that treatments can be read with these credentials. */
    fun test(): ConnectionReport {
        val status = parse(http.get(url("status.json", emptyList()), headers()))
        val name = (status.firstOrNull()?.get("name") as? String) ?: "nightscout"
        val version = status.firstOrNull()?.get("version") as? String
        fetch("treatments.json", emptyList(), count = 1)
        val newest = fetch("entries/sgv.json", emptyList(), count = 1).firstOrNull()?.let { (it["date"] as? Number)?.toLong() }
        return ConnectionReport(listOfNotNull(name, version).joinToString(" "), emptyMap(), newest)
    }

    // --- internals ---

    private fun cursor(block: suspend SequenceScope<Document>.() -> Unit): DocCursor = ListCursor(sequence(block).iterator())

    private fun dateRange(field: String, startMs: Long, endMs: Long) = listOf("find[$field][\$gt]" to startMs.toString(), "find[$field][\$lte]" to endMs.toString())
    private fun isoRange(field: String, w: Span) = listOf("find[$field][\$gt]" to SyncPlanner.iso(w.startMs), "find[$field][\$lte]" to SyncPlanner.iso(w.endMs))

    /** Cuts [span] into windows of at most [windowMs]; a window whose answer fills the limit is split in half and asked again. */
    private fun windowed(span: Span, windowMs: Long, fetchWindow: (Span) -> List<Document>): Sequence<Document> = sequence {
        var start = span.startMs
        while (start < span.endMs) {
            val end = minOf(start + windowMs, span.endMs)
            yieldAll(adaptive(Span(start, end), fetchWindow))
            start = end
        }
    }

    private fun adaptive(w: Span, fetchWindow: (Span) -> List<Document>): Sequence<Document> = sequence {
        val docs = fetchWindow(w)
        if (docs.size >= LIMIT && w.endMs - w.startMs > MIN_SPLIT_MS) {
            val mid = w.startMs + (w.endMs - w.startMs) / 2
            yieldAll(adaptive(Span(w.startMs, mid), fetchWindow))
            yieldAll(adaptive(Span(mid, w.endMs), fetchWindow))
        } else yieldAll(docs)
    }

    private fun fetch(path: String, query: List<Pair<String, String>>, count: Int = LIMIT): List<Document> =
        parse(http.get(url(path, query + ("count" to count.toString())), headers()))

    private fun url(path: String, query: List<Pair<String, String>>): String {
        val all = if (auth is RestAuth.Token) query + ("token" to auth.value) else query
        val qs = all.joinToString("&") { (k, v) -> "${URLEncoder.encode(k, "UTF-8")}=${URLEncoder.encode(v, "UTF-8")}" }
        return "$base/api/v1/$path" + if (qs.isEmpty()) "" else "?$qs"
    }

    private fun headers(): Map<String, String> =
        if (auth is RestAuth.ApiSecret) mapOf("api-secret" to sha1(auth.value)) else emptyMap()

    /** Nightscout answers with a JSON array (or one object for status). */
    private fun parse(body: String): List<Document> {
        val text = body.trim()
        if (text.isEmpty()) return emptyList()
        return try {
            if (text.startsWith("[")) (Document.parse("{\"r\":$text}")["r"] as List<*>).filterIsInstance<Document>() else listOf(Document.parse(text))
        } catch (e: Exception) {
            throw RestException("Nightscout sent an answer the app could not read. Is the address a Nightscout site?")
        }
    }

    companion object {
        const val LIMIT = 5000
        const val MAX_PROFILES = 300
        private const val HOUR = 3_600_000L
        private const val GLUCOSE_WINDOW_MS = 24 * HOUR
        private const val TREATMENT_WINDOW_MS = 48 * HOUR
        private const val IOB_WINDOW_MS = 24 * HOUR
        private const val MIN_SPLIT_MS = 10 * 60_000L

        /** Accepts "site.example", "https://site.example/" or a link ending in /api/v1; returns "https://site.example". */
        fun normalizeUrl(input: String): String {
            var s = input.trim().trimEnd('/')
            if (!s.contains("://")) s = "https://$s"
            s = s.removeSuffix("/api/v1").trimEnd('/')
            require(s.startsWith("https://")) { "The address must start with https:// (Android blocks plain http)." }
            return s
        }

        fun sha1(text: String): String = MessageDigest.getInstance("SHA-1").digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    }
}
