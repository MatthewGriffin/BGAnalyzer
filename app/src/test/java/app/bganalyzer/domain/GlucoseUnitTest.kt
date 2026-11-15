package app.bganalyzer.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class GlucoseUnitTest {
    @Test
    fun mmolProfileValueIsConvertedToMgdl() {
        // The user's real ISF: 12.1 mmol/L per unit is about 218 mg/dL per unit.
        assertEquals(217.8, GlucoseUnit.MMOL.toMgdl(12.1), 1e-9)
    }

    @Test
    fun mgdlValueIsLeftAlone() {
        assertEquals(100.0, GlucoseUnit.MGDL.toMgdl(100.0), 0.0)
        assertEquals(100.0, GlucoseUnit.MGDL.fromMgdl(100.0), 0.0)
    }

    @Test
    fun conversionRoundTrips() {
        assertEquals(5.5, GlucoseUnit.MMOL.fromMgdl(GlucoseUnit.MMOL.toMgdl(5.5)), 1e-9)
        assertEquals(3.0, GlucoseUnit.MMOL.fromMgdl(54.0), 1e-9)
    }

    @Test
    fun nightscoutUnitsAreParsed() {
        assertEquals(GlucoseUnit.MMOL, GlucoseUnit.fromNightscout("mmol"))
        assertEquals(GlucoseUnit.MMOL, GlucoseUnit.fromNightscout("mmol/L"))
        assertEquals(GlucoseUnit.MGDL, GlucoseUnit.fromNightscout("mg/dl"))
        assertNull(GlucoseUnit.fromNightscout(null))
        assertNull(GlucoseUnit.fromNightscout("stone"))
    }
}
