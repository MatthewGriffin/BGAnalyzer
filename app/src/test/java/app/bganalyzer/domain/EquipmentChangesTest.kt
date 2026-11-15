package app.bganalyzer.domain

import app.bganalyzer.data.GlucoseReadingEntity
import app.bganalyzer.data.TreatmentEntity
import org.junit.Assert.*
import org.junit.Test

class EquipmentChangesTest {
    private val day = 86_400_000L
    private fun t(time: Long, type: String, valid: Boolean = true) =
        TreatmentEntity("id$time$type", time, type, null, null, false, null, null, null, valid, null, "{}")
    private fun readings(fromDay: Int, toDay: Int, mgdl: Double) =
        (fromDay * 288 until toDay * 288).map { GlucoseReadingEntity(it * 300_000L, mgdl) }

    @Test fun aSiteAndInsulinChangeLoggedTogetherIsOneChange() {
        val list = EquipmentChanges.from(listOf(t(10 * day, "Site Change"), t(10 * day + 50, "Insulin Change"), t(14 * day, "Sensor Start"), t(20 * day, "Meal Bolus"), t(21 * day, "Site Change", valid = false)))
        assertEquals(listOf("Insulin + Site", "Sensor"), list.map { it.label })
        assertEquals(listOf(10 * day, 14 * day), list.map { it.startMs })
    }

    @Test fun comparesTheDaysAroundAChangeAndStopsAtTheNeighbour() {
        val changes = listOf(EquipmentChange(10 * day, listOf("Site")), EquipmentChange(13 * day, listOf("Site")))
        val res = EquipmentChanges.compare(readings(0, 30, 120.0), changes, 0, 30 * day)
        assertEquals(7.0, res[0].before.days, 1e-9) // no earlier change: the full 7 days
        assertEquals(3.0, res[0].after.days, 1e-9)  // stops at the next one
        assertEquals(3.0, res[1].before.days, 1e-9)
        assertEquals(7.0, res[1].after.days, 1e-9)
        assertTrue(res.all { it.before.enough && it.after.enough })
    }

    @Test fun onlyChangesInThePeriodAreReported() {
        val changes = listOf(EquipmentChange(2 * day, listOf("Site")), EquipmentChange(12 * day, listOf("Sensor")))
        val res = EquipmentChanges.compare(readings(0, 20, 120.0), changes, 5 * day, 20 * day)
        assertEquals(listOf("Sensor"), res.map { it.change.label })
        assertEquals(7.0, res[0].before.days, 1e-9) // the earlier change is 10 days away, so the window is the full 7
    }
}
