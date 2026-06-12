# NBA Stats Tracker

Automated season tracker for all 30 NBA teams.

A scheduled GitHub Actions workflow pulls each day's game results from the
[BALLDONTLIE](https://www.balldontlie.io) API, stores them in SQLite, and
publishes the data to a static site where any team can be analyzed or
compared head to head.

Live site: [nba.div23.app](https://nba.div23.app)

![Season chart](season_chart.png)

## How it works

`fetch_games.py` fetches the full season's games (cursor pagination,
rate-limit throttling), upserts them into `games.db` keyed on game id, and
writes `docs/data.json` along with the chart above. The workflow in
`.github/workflows/update.yml` runs this daily and commits the refreshed
files, which redeploys the GitHub Pages site.

Since loads are upserts, the pipeline is idempotent: re-running it any number
of times produces the same database state with no duplicate rows.

The site itself is a single static page (vanilla JS, animated SVG charts)
that reads `data.json`. The API key is only used server-side by the pipeline,
supplied through the `BALLDONTLIE_API_KEY` environment variable locally and a
repository secret in CI.

## Stack

Python, requests, matplotlib, SQLite, GitHub Actions, GitHub Pages.
