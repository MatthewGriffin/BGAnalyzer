package app.bganalyzer.mongo

import android.net.DnsResolver
import com.mongodb.spi.dns.DnsClient
import com.mongodb.spi.dns.DnsException
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit

/**
 * Looks up the SRV and TXT records behind a `mongodb+srv://` address through Android's resolver.
 * Passed to the MongoDB driver in place of its JNDI lookup, which does not exist on Android.
 */
class AndroidDnsClient(private val timeoutSeconds: Long = 10) : DnsClient {
    override fun getResourceRecordData(name: String, type: String): List<String> {
        val typeCode = when (type) {
            "SRV" -> DnsAnswerParser.TYPE_SRV
            "TXT" -> DnsAnswerParser.TYPE_TXT
            else -> throw DnsException("Unsupported DNS record type $type", IllegalArgumentException(type))
        }
        val answer = CompletableFuture<ByteArray?>()
        val callback = object : DnsResolver.Callback<ByteArray> {
            override fun onAnswer(response: ByteArray, rcode: Int) {
                // A non-zero code (such as "no such name") means there are no records to read.
                answer.complete(if (rcode == 0) response else null)
            }

            override fun onError(error: DnsResolver.DnsException) {
                answer.completeExceptionally(error)
            }
        }
        try {
            @Suppress("DEPRECATION") // The replacement only exists on Android 16 and later.
            DnsResolver.getInstance().rawQuery(
                null, name, DnsResolver.CLASS_IN, typeCode, DnsResolver.FLAG_EMPTY, Runnable::run, null, callback,
            )
            val response = answer.get(timeoutSeconds, TimeUnit.SECONDS) ?: return emptyList()
            return DnsAnswerParser.parse(response, typeCode)
        } catch (e: Exception) {
            throw DnsException("DNS lookup of $type records for $name failed", e)
        }
    }
}
