# BGAnalyzer

Android app that reads glucose and insulin data from a Nightscout MongoDB database (uploaded by AndroidAPS) and suggests setting changes to improve time in range. In development: the app can currently connect to the database and report what it finds.

## Build

Requires the Android SDK (platform 37) and a `local.properties` file with `sdk.dir=<path to the SDK>`.

```bash
./gradlew test assembleDebug
```

On-device tests run on a connected phone or emulator. See `app/src/androidTest/java/app/bganalyzer/mongo/MongoOnAndroidTest.kt` for the MongoDB address argument.

## Layout

- `app/`: the Android app (Kotlin, Compose, Room).
- `reference/`: unmodified AndroidAPS sources used as the reference for ported logic (AGPL-3.0).

The earlier Python desktop app is no longer developed. Its final state is on the `desktop-final` branch.
