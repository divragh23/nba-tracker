# NBA Stats Tracker

An automated data pipeline and website covering all 30 NBA teams. Every day a
GitHub Actions workflow pulls the season's game results from the
[BALLDONTLIE](https://www.balldontlie.io) API, upserts them into a SQLite
database (idempotent — safe to re-run, never duplicates), exports the data as
JSON, and commits the refreshed files back to this repo.

**Live site:** <https://divragh23.github.io/nba-tracker/> — pick any team for
an animated season breakdown, or compare two teams head to head.

![Season chart](season_chart.png)

## How it works

ETL, end to end:

- **Extract** — fetches every game of the current season (~14 paginated API
  requests, throttled to respect the free tier's rate limit).
- **Transform** — one clean row per finished game: teams, scores, playoff flag.
- **Load** — upserted into SQLite keyed on the API's game id, then exported to
  `docs/data.json`, which the static site reads. No API key ever reaches the
  browser.

Running it needs a free BALLDONTLIE key in the `BALLDONTLIE_API_KEY`
environment variable (locally) or repository secret (GitHub Actions).

## Files

| File | What it is |
|------|------------|
| `fetch_games.py` | The pipeline: extract, transform, load, export, chart. |
| `docs/index.html` | The website (served by GitHub Pages from `docs/`). |
| `docs/data.json` | Season data the site reads (regenerated daily). |
| `.github/workflows/update.yml` | The daily schedule that runs everything. |
| `games.db` | The SQLite database. |
| `season_chart.png` | Featured-team chart shown above. |
