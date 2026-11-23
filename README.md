# BGAnalyzer

Android app that reads glucose and insulin data from a Nightscout site (uploaded by AndroidAPS), shows how glucose behaves, and runs an AndroidAPS-style **Autotune** to suggest basal, insulin sensitivity and carb ratio values for a new profile. It gives advice only: it never changes a pump, a loop or a profile.

> **Warning: you are responsible for any change you make to basal rates, insulin sensitivity, carb ratio or any other pump or loop setting.** BGAnalyzer is not a medical device and gives suggestions only, based on past data that may be incomplete or wrong. Check every change with your diabetes care team before using it. Use at your own risk, with no warranty (see `LICENSE`).

## What it does

- **Overview:** glucose chart with insulin, carbs, basal and profile changes, and time in range.
- **Autotune:** replays recent days (4 AM to 4 AM) against your insulin and carb records, with confidence per value, and lays the result out as tables ready to copy into a profile.
- **Patterns:** trends only (glucose by time of day, post-meal rises, loop basal against profile, before/after profile changes). Days with bad data (for example a pump failure) can be excluded.
- **Data sources:** the Nightscout MongoDB database directly, or the Nightscout REST API (read-only, incremental).
- **Background sync:** every 3 hours when online (can be switched off on the Connection tab).
- **Backup:** encrypted backup and restore of everything the app saves.

## Build

Requires the Android SDK (platform 37) and a `local.properties` file with `sdk.dir=<path to the SDK>`. There are no store builds: build it yourself.

```bash
./gradlew test assembleDebug
```

On-device tests run on a connected phone or emulator; some need a throwaway MongoDB or a Nightscout address as a test argument (see the comments in `app/src/androidTest`). Never point them at data you care about.

## Layout

- `app/`: the Android app (Kotlin, Jetpack Compose, Room).
- `reference/`: unmodified AndroidAPS sources used as the reference for the ported logic (AGPL-3.0). Not compiled into the app.

The earlier Python desktop app is no longer developed. Its final state is on the `desktop-final` branch.

## Credits and sources

This project builds on other open-source work. Thank you to everyone behind it.

- **[AndroidAPS](https://github.com/nightscout/AndroidAPS)** (AGPL-3.0): the Autotune logic (core, prep, insulin and IOB model) and the profile modifier handling are ported from AndroidAPS 3.4.2.1, commit `1393357107a2b27ba153df31d64e745efd771ef2`. The pinned source files and their hashes are in `reference/aaps/manifest.json`, and the app is tested against AndroidAPS's own Autotune test cases.
- **[oref0](https://github.com/openaps/oref0)** (MIT): the OpenAPS reference implementation that AndroidAPS's Autotune is itself a port of.
- **[Nightscout (cgm-remote-monitor)](https://github.com/nightscout/cgm-remote-monitor)** (AGPL-3.0): the data store and REST API the app reads from.
- **[MongoDB Java driver](https://github.com/mongodb/mongo-java-driver)** (Apache-2.0): used for the direct database source.
- Also built on [AndroidX](https://developer.android.com/jetpack/androidx) (Compose, Room) and [Kotlin](https://github.com/JetBrains/kotlin).

## Licence

AGPL-3.0 (see `LICENSE`), because the Autotune code is ported from AndroidAPS and carries its licence. The files in `reference/aaps/` keep their original AGPL-3.0 licence (`reference/aaps/LICENSE.txt`). The repository is private; if it is ever shared, it will be as source only for people to build themselves.
