package app.bganalyzer.mongo

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayOutputStream

class DnsAnswerParserTest {
    private class Packet {
        val out = ByteArrayOutputStream()
        fun u8(v: Int) = apply { out.write(v) }
        fun u16(v: Int) = apply { out.write(v shr 8); out.write(v and 0xFF) }
        fun name(name: String) = apply {
            name.split('.').filter { it.isNotEmpty() }.forEach { u8(it.length); out.write(it.toByteArray()) }
            u8(0)
        }
        fun pointer(offset: Int) = apply { u16(0xC000 or offset) }
        fun header(questions: Int, answers: Int) = apply {
            u16(0x1234); u16(0x8180); u16(questions); u16(answers); u16(0); u16(0)
        }
        fun bytes(): ByteArray = out.toByteArray()
    }

    /** A response to an SRV question with two answers; the second target is compressed against the question name. */
    private fun srvResponse(): ByteArray {
        val p = Packet().header(questions = 1, answers = 2)
        // Question name starts at offset 12: _mongodb(8) _tcp(4) cluster0(8) example(7) net(3).
        p.name("_mongodb._tcp.cluster0.example.net").u16(33).u16(1)
        val clusterOffset = 12 + 9 + 5 // skips "_mongodb" and "_tcp" labels
        // Answer 1: full target name.
        val target1 = Packet().u16(0).u16(5).u16(27017).name("shard-00.cluster0.example.net").bytes()
        p.pointer(12).u16(33).u16(1).u16(0).u16(60).u16(target1.size); p.out.write(target1)
        // Answer 2: "shard-01" followed by a pointer to "cluster0.example.net".
        val target2 = Packet().u16(0).u16(5).u16(27018).u8(8).also { it.out.write("shard-01".toByteArray()) }
            .pointer(clusterOffset).bytes()
        p.pointer(12).u16(33).u16(1).u16(0).u16(60).u16(target2.size); p.out.write(target2)
        return p.bytes()
    }

    @Test
    fun srvRecordsAreReadInDriverFormat() {
        assertEquals(
            listOf("0 5 27017 shard-00.cluster0.example.net.", "0 5 27018 shard-01.cluster0.example.net."),
            DnsAnswerParser.parse(srvResponse(), DnsAnswerParser.TYPE_SRV),
        )
    }

    @Test
    fun otherRecordTypesAreIgnored() {
        assertEquals(emptyList<String>(), DnsAnswerParser.parse(srvResponse(), DnsAnswerParser.TYPE_TXT))
    }

    @Test
    fun txtStringsAreJoined() {
        val p = Packet().header(questions = 1, answers = 1).name("cluster0.example.net").u16(16).u16(1)
        val first = "authSource=admin&"
        val second = "replicaSet=atlas-abc-shard-0"
        p.pointer(12).u16(16).u16(1).u16(0).u16(60).u16(first.length + second.length + 2)
        p.u8(first.length); p.out.write(first.toByteArray())
        p.u8(second.length); p.out.write(second.toByteArray())
        assertEquals(
            listOf("authSource=admin&replicaSet=atlas-abc-shard-0"),
            DnsAnswerParser.parse(p.bytes(), DnsAnswerParser.TYPE_TXT),
        )
    }

    @Test
    fun truncatedResponseIsRejected() {
        val full = srvResponse()
        assertThrows(IllegalArgumentException::class.java) {
            DnsAnswerParser.parse(full.copyOf(full.size - 10), DnsAnswerParser.TYPE_SRV)
        }
    }
}
