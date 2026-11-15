package app.bganalyzer.mongo

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
}
