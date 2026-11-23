package app.bganalyzer.domain

import java.time.ZoneId

/**
 * Picks the time zone used to cut days and hours. A profile can carry a fixed zone such as "UTC", which has no summer
 * time, so a day would start an hour off for half the year. A named region (Europe/London) follows summer time, so the
 * newest profile that names a region wins; with none, the phone's own zone is used.
 */
object ZoneResolver {
    /** [names] are the profiles' zone names, newest first. */
    fun resolve(names: List<String?>, fallback: ZoneId = ZoneId.systemDefault()): ZoneId =
        names.asSequence().filterNotNull().filter { '/' in it }.mapNotNull { runCatching { ZoneId.of(it) }.getOrNull() }.firstOrNull() ?: fallback
}
