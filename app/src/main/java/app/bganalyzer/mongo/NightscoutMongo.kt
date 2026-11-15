package app.bganalyzer.mongo

import com.mongodb.ConnectionString
import com.mongodb.MongoClientSettings
import com.mongodb.client.MongoClient
import com.mongodb.client.MongoClients
import com.mongodb.client.model.Sorts
import com.mongodb.spi.dns.DnsClient
import org.bson.Document
import java.util.concurrent.TimeUnit

/** What a connection test found in the Nightscout database. */
data class ConnectionReport(
    val database: String,
    /** Document counts for the Nightscout collections the app reads, in a fixed order. */
    val collectionCounts: Map<String, Long>,
    /** Time of the newest glucose entry in epoch milliseconds, or null when there are none. */
    val newestEntryMs: Long?,
)

/** Read-only access to a Nightscout MongoDB database. All calls block, so run them off the main thread. */
object NightscoutMongo {
    val COLLECTIONS = listOf("entries", "treatments", "profile", "devicestatus")

    fun open(uri: String, dnsClient: DnsClient = AndroidDnsClient()): MongoClient {
        val settings = MongoClientSettings.builder()
            .dnsClient(dnsClient)
            .applyConnectionString(ConnectionString(uri.trim(), dnsClient))
            .applicationName("BGAnalyzer")
            .applyToClusterSettings { it.serverSelectionTimeout(15, TimeUnit.SECONDS) }
            .applyToSocketSettings { it.connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS) }
            .build()
        return MongoClients.create(settings)
    }

    /** The database named in the address path, or null when the address does not name one. */
    fun databaseInUri(uri: String): String? =
        runCatching { ConnectionString(uri.trim(), NoDns).database }.getOrNull()?.takeIf { it.isNotBlank() }

    /** Connects, counts the Nightscout collections and finds the newest glucose entry. Throws on any failure. */
    fun test(uri: String, database: String, dnsClient: DnsClient = AndroidDnsClient()): ConnectionReport =
        open(uri, dnsClient).use { client ->
            val db = client.getDatabase(database)
            db.runCommand(Document("ping", 1))
            val counts = COLLECTIONS.associateWith { db.getCollection(it).estimatedDocumentCount() }
            val newest = db.getCollection("entries")
                .find().sort(Sorts.descending("date")).limit(1).first()
                ?.let { (it["date"] as? Number)?.toLong() }
            ConnectionReport(database, counts, newest)
        }

    /** Used only to read the address text, where no lookup is wanted. */
    private object NoDns : DnsClient {
        override fun getResourceRecordData(name: String, type: String): List<String> = emptyList()
    }
}
