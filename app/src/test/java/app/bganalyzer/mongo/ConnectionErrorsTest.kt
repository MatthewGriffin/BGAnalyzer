package app.bganalyzer.mongo

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionErrorsTest {
    @Test
    fun addressAndPasswordAreNeverShown() {
        val error = IllegalStateException(
            "Could not use mongodb+srv://reader:s3cret@cluster0.example.net/?x=1 here",
            RuntimeException("Timed out"),
        )
        val shown = ConnectionErrors.describe(error)
        assertFalse(shown, shown.contains("s3cret"))
        assertEquals("Could not use mongodb://(address hidden) here\nTimed out", shown)
    }

    @Test
    fun errorWithoutMessageFallsBackToItsName() {
        assertEquals("IllegalStateException", ConnectionErrors.describe(IllegalStateException()))
    }

    @Test
    fun aNightscoutTokenInAnAddressIsNeverShown() {
        val shown = ConnectionErrors.describe(java.net.MalformedURLException("bad https://site.example/api/v1/entries.json?count=1&token=abc123-secret&x=2"))
        assertFalse(shown, shown.contains("abc123"))
        assertTrue(shown, shown.contains("token=(hidden)"))
    }
}
