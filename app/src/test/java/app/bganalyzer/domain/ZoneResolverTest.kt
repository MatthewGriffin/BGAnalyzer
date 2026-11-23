package app.bganalyzer.domain

import java.time.ZoneId
import org.junit.Test
import org.junit.Assert.assertEquals

class ZoneResolverTest {
    private val phone = ZoneId.of("Europe/Paris")

    @Test fun regionZoneIsUsed() = assertEquals(ZoneId.of("Europe/London"), ZoneResolver.resolve(listOf("Europe/London"), phone))

    @Test fun fixedUtcIsSkippedForAnOlderRegion() = assertEquals(ZoneId.of("Europe/London"), ZoneResolver.resolve(listOf("UTC", null, "Europe/London"), phone))

    @Test fun onlyFixedZonesFallBackToThePhone() = assertEquals(phone, ZoneResolver.resolve(listOf("UTC", "GMT", "bogus"), phone))

    @Test fun nothingFallsBackToThePhone() = assertEquals(phone, ZoneResolver.resolve(emptyList(), phone))

    @Test fun summerTimeIsFollowed() {
        val zone = ZoneResolver.resolve(listOf("Europe/London"), phone)
        assertEquals(3600, zone.rules.getOffset(java.time.Instant.parse("2027-07-01T12:00:00Z")).totalSeconds)
    }
}
