# BGAnalyzer

Native Linux desktop application in development for reviewing Nightscout glucose and treatment history. Current working features: background read-only imports, local SQLite history, duration-weighted glucose summaries, a glucose timeline, treatment records, stale-data indicators, and local JSON summary export.

## Run

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/):

```bash
uv sync --locked
uv run --locked bganalyzer
```

Alternatively, with this workspace's existing environment:

```bash
.venv/bin/python -m bganalyzer
```

Open **Connection**, enter your MongoDB Atlas database name and read-only connection URI, choose the history window, and select **Save connection and import**. The URI is stored in the desktop keyring when selected, never in config.json. Existing Atlas credentials remain usable. See [MongoDB setup](docs/ATLAS_SETUP.md).

MongoDB is the only remote data source for both today's automatic updates and historical imports. No Nightscout HTTP requests or fallback are made. The daily graph has previous/next-day controls; report summaries independently cover the selected multi-day range. Cached records remain available offline. A linked event timeline shows recorded carbs, boluses, SMBs and basal events beneath the glucose graph. Click a marker for source details, or double-click a treatment row to open its day.

The **Basal readiness** tab lists individual hourly candidates. Select a row for a plain-English explanation of the observed pattern, why later glucose readings affect that basal hour, and whether the evidence agrees or conflicts. Calculation details and individual readings are optional. Withheld calculations remain labelled unvalidated. **Data quality** is the fourth tab. Summary exports retain deterministic glucose-metric explanations and per-reading contributions.

The app-managed local model runtime is implemented, but the current window has no local-AI explanation controls. Hourly explanations use retained calculation evidence directly. See [Local AI setup and limits](docs/LOCAL_AI.md).

## Development status

See [current project state](docs/PROJECT_STATE.md) and [docs/PROGRESS.md](docs/PROGRESS.md) for the verified checkpoint and next implementation work. The interrupted implementation included incomplete insulin math and always-true eligibility checks. Candidate release depends on eligibility checks; withheld runs can display explicitly labelled descriptive calculations. The local inference prototype has been replaced with the verified, app-managed runtime described above.

Validated AAPS Autotune parity, historical delivery reconstruction, broader evidence analysis, and Flatpak distribution remain unfinished. This is a working development dashboard, not the completed recommendation product.

The [implementation specification](IMPLEMENTATION_PLAN.md) remains the product contract. Never commit credentials, clinical records, model weights, or local databases. No application request changes Nightscout, AAPS, or pump settings.

## Verify

```bash
QT_QPA_PLATFORM=offscreen uv run --locked pytest -q
uv run --locked ruff check src tests --select F821,F822,F823,E9
```

Tests use synthetic data and temporary directories, without Nightscout access. A separate one-time live import check was performed with counts-only output and its temporary data removed.
