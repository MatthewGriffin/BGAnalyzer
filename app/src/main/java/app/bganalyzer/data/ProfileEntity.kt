package app.bganalyzer.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * One uploaded Nightscout profile document. Schedules stay in [rawJson] in the profile's own units
 * (AAPS uploads ISF and targets in the profile units, so mmol profiles must be converted when read).
 */
@Entity(tableName = "profiles")
data class ProfileEntity(
    @PrimaryKey val id: String,
    val startMs: Long,
    val defaultProfile: String?,
    val units: String?,
    val timezone: String?,
    val rawJson: String,
)
