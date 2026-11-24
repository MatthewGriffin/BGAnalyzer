package app.bganalyzer.sync

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StaleAlertTest {
    private val h = 3_600_000L
    @Test fun freshDataDoesNotAlert() = assertFalse(StaleAlert.shouldAlert(100 * h, 101 * h, 0))
    @Test fun oldDataAlerts() = assertTrue(StaleAlert.shouldAlert(100 * h, 103 * h, 0))
    @Test fun noRepeatWithinSixHours() = assertFalse(StaleAlert.shouldAlert(100 * h, 105 * h, 102 * h))
    @Test fun repeatsAfterSixHours() = assertTrue(StaleAlert.shouldAlert(100 * h, 109 * h, 102 * h))
    @Test fun noDataAtAllDoesNotAlert() = assertFalse(StaleAlert.shouldAlert(null, 10 * h, 0))
}
