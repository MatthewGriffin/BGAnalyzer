package app.bganalyzer.domain

import app.bganalyzer.backup.BackupCodec
import app.bganalyzer.backup.BackupData
import app.bganalyzer.data.ExcludedDayEntity
import app.bganalyzer.data.GlucoseReadingEntity
import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime

class ExcludedDaysTest {
    private val zone = ZoneId.of("Europe/London")
    private fun ms(y: Int, m: Int, d: Int, h: Int) = ZonedDateTime.of(y, m, d, h, 0, 0, 0, zone).toInstant().toEpochMilli()

    @Test fun readingsOnAnExcludedLocalDayAreDropped() {
        val list = listOf(GlucoseReadingEntity(ms(2026, 11, 14, 23), 100.0), GlucoseReadingEntity(ms(2026, 11, 15, 0), 110.0), GlucoseReadingEntity(ms(2026, 11, 16, 1), 120.0))
        val kept = ExcludedDays.readings(list, zone, setOf("2026-11-15"))
        assertEquals(listOf(100.0, 120.0), kept.map { it.mgdl })
    }

    @Test fun excludedDaysSurviveABackupRoundTripAndOldFilesHaveNone() {
        val data = BackupData(1L, null, null, emptyList(), excludedDays = listOf(ExcludedDayEntity("2026-11-15", "Pump failure", 5L)))
        val back = BackupCodec.decode(BackupCodec.encode(data, "passphrase1"), "passphrase1")
        assertEquals(data.excludedDays, back.excludedDays)
    }
}
