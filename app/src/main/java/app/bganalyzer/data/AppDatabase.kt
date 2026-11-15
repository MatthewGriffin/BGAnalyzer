package app.bganalyzer.data

import android.content.Context
import androidx.room.AutoMigration
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

/**
 * Saved user data lives here, so schema changes must be migrations that keep existing rows. Never use a
 * destructive fallback. Version 2 only adds tables.
 */
@Database(
    entities = [GlucoseReadingEntity::class, TreatmentEntity::class, ProfileEntity::class],
    version = 2,
    exportSchema = true,
    autoMigrations = [AutoMigration(from = 1, to = 2)],
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun glucoseReadingDao(): GlucoseReadingDao
    abstract fun treatmentDao(): TreatmentDao
    abstract fun profileDao(): ProfileDao

    companion object {
        @Volatile
        private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(context.applicationContext, AppDatabase::class.java, "bganalyzer.db")
                .build()
                .also { instance = it }
        }
    }
}
