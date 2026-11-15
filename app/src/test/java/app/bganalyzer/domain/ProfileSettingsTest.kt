package app.bganalyzer.domain

import org.junit.Assert.*
import org.junit.Test

class ProfileSettingsTest {
    private fun profile(units: String) = app.bganalyzer.data.ProfileEntity(
        "p", 0, "main", units, "UTC",
        """{"store":{"main":{"units":"$units","sens":[{"time":"00:00","timeAsSeconds":0,"value":12.0}],"carbratio":[{"time":"00:00","timeAsSeconds":0,"value":5.0}]}}}""",
    )

    @Test fun mmolSensitivityIsConvertedToMgdl() {
        val s = ProfileSettings.of(profile("mmol/L"))
        assertEquals(216.0, s.isfMgdlAt(3)!!, 1e-9); assertEquals(5.0, s.carbRatioAt(3)!!, 1e-9)
    }

    @Test fun mgdlSensitivityIsKept() = assertEquals(12.0, ProfileSettings.of(profile("mg/dl")).isfMgdlAt(3)!!, 1e-9)
}

class ProfileSettingsModifierTest {
    @Test fun percentageDividesSensitivityAndCarbRatio() {
        val s = ProfileSettings(listOf(BasalStep(0, 100.0)), listOf(BasalStep(0, 10.0))).modified(120, 0)
        assertEquals(83.333, s.isfMgdlAt(3)!!, 0.01); assertEquals(8.333, s.carbRatioAt(3)!!, 0.01)
    }

    @Test fun jsonBodyIsReadWithItsOwnUnits() {
        val j = """{"units":"mmol","sens":[{"timeAsSeconds":0,"value":10}],"carbratio":[{"timeAsSeconds":0,"value":6}]}"""
        assertEquals(180.0, ProfileSettings.fromJson(j).isfMgdlAt(0)!!, 1e-9)
    }
}

class ProfileSettingsUnitsGuessTest {
    @Test fun missingUnitsWithSmallSensitivityIsTreatedAsMmol() =
        assertEquals(180.0, ProfileSettings.fromJson("""{"sens":[{"timeAsSeconds":0,"value":10}]}""").isfMgdlAt(0)!!, 1e-9)
}
