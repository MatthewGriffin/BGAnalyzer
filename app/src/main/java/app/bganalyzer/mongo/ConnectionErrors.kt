package app.bganalyzer.mongo

/**
 * Turns a connection failure into text for the screen. The MongoDB address contains the password,
 * so anything that looks like an address is cut out of the message before it is shown.
 */
object ConnectionErrors {
    private val address = Regex("""mongodb(\+srv)?://\S+""")

    fun describe(error: Throwable): String {
        val causes = generateSequence(error) { it.cause }.take(6).toList()
        val text = causes.mapNotNull { it.message?.takeIf(String::isNotBlank) }.distinct().joinToString("\n")
            .ifBlank { error.javaClass.simpleName }
        return redact(text)
    }

    fun redact(text: String): String = address.replace(text, "mongodb://(address hidden)")
}
