package app.bganalyzer.mongo

/**
 * Reads the answer records out of a raw DNS response, in the text form the MongoDB driver expects:
 * SRV records as "priority weight port target." and TXT records as their text.
 *
 * Android has no JNDI, which the driver normally uses for these lookups, so the app asks Android's
 * own resolver for the raw response and parses it here.
 */
object DnsAnswerParser {
    const val TYPE_TXT = 16
    const val TYPE_SRV = 33

    /** Returns the data of every answer record of [wantedType]. Throws IllegalArgumentException on a malformed response. */
    fun parse(response: ByteArray, wantedType: Int): List<String> {
        try {
            val questionCount = u16(response, 4)
            val answerCount = u16(response, 6)
            var pos = 12
            repeat(questionCount) { pos = skipName(response, pos) + 4 }
            val records = mutableListOf<String>()
            repeat(answerCount) {
                pos = skipName(response, pos)
                val type = u16(response, pos)
                val length = u16(response, pos + 8)
                val data = pos + 10
                require(data + length <= response.size) { "record runs past the end of the response" }
                if (type == wantedType) {
                    when (type) {
                        TYPE_SRV -> records += "${u16(response, data)} ${u16(response, data + 2)} " +
                            "${u16(response, data + 4)} ${readName(response, data + 6)}"
                        TYPE_TXT -> records += readText(response, data, length)
                    }
                }
                pos = data + length
            }
            return records
        } catch (e: IndexOutOfBoundsException) {
            throw IllegalArgumentException("DNS response is cut short", e)
        }
    }

    private fun u8(b: ByteArray, i: Int) = b[i].toInt() and 0xFF

    private fun u16(b: ByteArray, i: Int) = (u8(b, i) shl 8) or u8(b, i + 1)

    /** A TXT record is one or more length-prefixed strings, which belong together as one value. */
    private fun readText(b: ByteArray, start: Int, length: Int): String {
        val text = StringBuilder()
        var pos = start
        while (pos < start + length) {
            val n = u8(b, pos)
            text.append(String(b, pos + 1, n, Charsets.UTF_8))
            pos += 1 + n
        }
        return text.toString()
    }

    /** Returns the position just after the name that starts at [start]. */
    private fun skipName(b: ByteArray, start: Int): Int {
        var pos = start
        while (true) {
            val n = u8(b, pos)
            if (n == 0) return pos + 1
            if (n and 0xC0 == 0xC0) return pos + 2
            pos += 1 + n
        }
    }

    /** Reads a domain name, following compression pointers, and returns it with a trailing dot. */
    private fun readName(b: ByteArray, start: Int): String {
        val name = StringBuilder()
        var pos = start
        var jumps = 0
        while (true) {
            val n = u8(b, pos)
            when {
                n == 0 -> return if (name.isEmpty()) "." else name.toString()
                n and 0xC0 == 0xC0 -> {
                    require(++jumps <= 20) { "DNS name has a pointer loop" }
                    pos = ((n and 0x3F) shl 8) or u8(b, pos + 1)
                }
                else -> {
                    name.append(String(b, pos + 1, n, Charsets.US_ASCII)).append('.')
                    pos += 1 + n
                }
            }
        }
    }
}
