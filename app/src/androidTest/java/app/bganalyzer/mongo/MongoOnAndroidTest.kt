package app.bganalyzer.mongo

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.bson.Document
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNotNull
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Checks that the MongoDB driver really works on Android. These run on a device or emulator, not in CI.
 *
 * The database test needs a throwaway MongoDB and its address, for example:
 * `./gradlew :app:connectedDebugAndroidTest
 *  -Pandroid.testInstrumentationRunnerArguments.mongoUri=mongodb://user:pass@10.0.2.2:27017/?authSource=admin`
 * It writes to a database called `bganalyzer_probe`. Never point it at the real Nightscout database.
 */
@RunWith(AndroidJUnit4::class)
class MongoOnAndroidTest {
    @Test
    fun connectsLogsInAndReads() {
        val uri = InstrumentationRegistry.getArguments().getString("mongoUri")
        assumeNotNull(uri)
        NightscoutMongo.open(uri!!).use { client ->
            val entries = client.getDatabase("bganalyzer_probe").getCollection("entries")
            entries.drop()
            entries.insertMany(listOf(Document("sgv", 120).append("date", 1000L), Document("sgv", 130).append("date", 2000L)))
        }
        val report = NightscoutMongo.test(uri, "bganalyzer_probe")
        assertEquals(2L, report.collectionCounts["entries"])
        assertEquals(2000L, report.newestEntryMs)
    }

    /** Needs internet access. Uses long-lived public records. */
    @Test
    fun androidResolverReturnsSrvAndTxtRecords() {
        val dns = AndroidDnsClient()
        val srv = dns.getResourceRecordData("_imaps._tcp.gmail.com", "SRV")
        assertTrue("SRV records: $srv", srv.any { it.matches(Regex("""\d+ \d+ 993 imap\.gmail\.com\.""")) })
        val txt = dns.getResourceRecordData("gmail.com", "TXT")
        assertTrue("TXT records: $txt", txt.any { it.startsWith("v=spf1") })
        assertEquals(emptyList<String>(), dns.getResourceRecordData("no-such-name.bganalyzer.invalid", "TXT"))
    }
}
