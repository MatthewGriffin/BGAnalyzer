package app.bganalyzer.rest

import app.bganalyzer.sync.GlucoseEntryMapper
import app.bganalyzer.sync.Span
import app.bganalyzer.sync.TreatmentMapper
import org.junit.Assert.*
import org.junit.Test
import java.net.URLDecoder

class NightscoutRestTest {
    private class Fake(val answer: (String) -> String) : HttpGet {
        val urls = ArrayList<String>(); val headers = ArrayList<Map<String, String>>()
        override fun get(url: String, headers: Map<String, String>): String { urls += URLDecoder.decode(url, "UTF-8"); this.headers += headers; return answer(url) }
    }

    @Test fun normalizeUrlAcceptsCommonForms() {
        assertEquals("https://a.example", RestSyncSource.normalizeUrl("a.example"))
        assertEquals("https://a.example", RestSyncSource.normalizeUrl(" https://a.example/ "))
        assertEquals("https://a.example", RestSyncSource.normalizeUrl("https://a.example/api/v1/"))
        assertThrows(IllegalArgumentException::class.java) { RestSyncSource.normalizeUrl("http://a.example") }
    }

    @Test fun glucoseIsAskedByDateWindowsAndMapsToReadings() {
        val http = Fake { """[{"_id":"a","sgv":110,"date":1000,"type":"sgv"},{"_id":"b","sgv":120,"date":2000,"type":"sgv"}]""" }
        val docs = RestSyncSource("https://x.example", RestAuth.None, http).glucose(listOf(Span(0, 30 * 3_600_000L))).asSequence().toList()
        assertEquals(4, docs.size) // two windows, two entries each
        assertEquals(110.0, GlucoseEntryMapper.fromDocument(docs[0])!!.mgdl, 0.0)
        assertEquals(2, http.urls.size)
        assertTrue(http.urls[0].startsWith("https://x.example/api/v1/entries/sgv.json?find[date][\$gt]=0&find[date][\$lte]=86400000&count=5000"))
    }

    @Test fun aFullWindowIsSplitInHalf() {
        var calls = 0
        val http = Fake { url ->
            calls++
            // the first (whole) window comes back full, the halves do not
            if (calls == 1) "[" + (1..RestSyncSource.LIMIT).joinToString(",") { """{"_id":"i$it","sgv":100,"date":$it}""" } + "]" else """[{"_id":"h$calls","sgv":100,"date":5}]"""
        }
        val docs = RestSyncSource("https://x.example", RestAuth.None, http).glucose(listOf(Span(0, 3_600_000L))).asSequence().toList()
        assertEquals(3, http.urls.size)
        assertEquals(2, docs.size)
    }

    @Test fun treatmentsAreAskedTwoWaysAndDeduplicated() {
        val rec = """{"_id":"t1","created_at":"2026-11-01T10:00:00.000Z","date":1793613600000,"eventType":"Meal Bolus","insulin":2.5,"carbs":30,"srvModified":5,"isValid":true}"""
        val http = Fake { "[$rec]" }
        val docs = RestSyncSource("https://x.example", RestAuth.None, http).treatments(listOf(Span(1793600000000L, 1793700000000L)), editedAfterMs = 4).asSequence().toList()
        assertEquals(1, docs.size)
        assertTrue(http.urls.any { it.contains("find[created_at][\$gt]=") })
        assertTrue(http.urls.any { it.contains("find[date][\$gt]=") })
        assertTrue(http.urls.any { it.contains("find[srvModified][\$gt]=4") })
        val t = TreatmentMapper.treatment(docs[0])!!
        assertEquals("t1", t.id); assertEquals(2.5, t.insulin!!, 0.0); assertEquals(1793613600000L, t.timestampMs)
    }

    @Test fun tokenGoesInTheQueryAndSecretIsHashedInAHeader() {
        val a = Fake { "[]" }
        RestSyncSource("https://x.example", RestAuth.Token("abc-123"), a).glucose(listOf(Span(0, 1000))).asSequence().toList()
        assertTrue(a.urls[0].contains("token=abc-123"))
        val b = Fake { "[]" }
        RestSyncSource("https://x.example", RestAuth.ApiSecret("secret"), b).glucose(listOf(Span(0, 1000))).asSequence().toList()
        assertEquals(RestSyncSource.sha1("secret"), b.headers[0]["api-secret"]); assertFalse(b.urls[0].contains("secret"))
        assertEquals("e5e9fa1ba31ecd1ae84f75caaa474f3a663f05f4", RestSyncSource.sha1("secret"))
    }

    @Test fun profilesKeepOnlyNewOnesAndLoopStatusUsesTheExistsFilter() {
        val http = Fake { """[{"_id":"p1","created_at":"2026-11-13T00:00:00.000Z"},{"_id":"p2","created_at":"2026-10-01T00:00:00.000Z"}]""" }
        val src = RestSyncSource("https://x.example", RestAuth.None, http)
        assertEquals(2, src.profiles(null).asSequence().count())
        assertEquals(1, src.profiles(java.time.Instant.parse("2026-11-12T12:00:00Z").toEpochMilli()).asSequence().count())
        src.iob(listOf(Span(0, 1000))).asSequence().toList()
        assertTrue(http.urls.last().contains("find[openaps.iob][\$exists]=true"))
    }

    @Test fun badAnswerGivesAClearError() {
        val e = assertThrows(RestException::class.java) { RestSyncSource("https://x.example", RestAuth.None, Fake { "<html>" }).glucose(listOf(Span(0, 1000))).asSequence().toList() }
        assertTrue(e.message!!.contains("could not read"))
    }
}

class RestBackupTest {
    @Test fun restSettingsSurviveABackupRoundTripAndOlderFilesHaveNone() {
        val data = app.bganalyzer.backup.BackupData(1L, null, null, emptyList(), rest = app.bganalyzer.backup.RestBackup("rest", "https://x.example", "token", "abc"))
        val back = app.bganalyzer.backup.BackupCodec.decode(app.bganalyzer.backup.BackupCodec.encode(data, "passphrase1"), "passphrase1")
        assertEquals(data.rest, back.rest)
        val none = app.bganalyzer.backup.BackupCodec.decode(app.bganalyzer.backup.BackupCodec.encode(app.bganalyzer.backup.BackupData(1L, null, null, emptyList()), "passphrase1"), "passphrase1")
        assertNull(none.rest)
    }
}
