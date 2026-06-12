"""
NBA Stats Tracker
-----------------
A small data pipeline (ETL) that:
  1. EXTRACT  - pulls EVERY game of the current NBA season (all 30 teams)
                from the BALLDONTLIE API, page by page.
  2. TRANSFORM - keeps one clean, neutral row per finished game
                (home team, away team, scores, playoff flag).
  3. LOAD     - upserts the rows into a SQLite database keyed on the API's
                game id, so re-running never creates duplicates.
Then it:
  - exports docs/data.json   -> read by the website in docs/
  - draws season_chart.png   -> the TEAM_NAME chart shown in the README

Run it by hand with:   python fetch_games.py
GitHub Actions runs it on a schedule (see .github/workflows/update.yml).
"""

import datetime
import json
import os
import sqlite3
import time

import requests
import matplotlib
matplotlib.use("Agg")          # lets matplotlib draw without a screen (needed on GitHub)
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
TEAM_NAME = "Los Angeles Lakers"   # the team featured in the README chart
API_BASE = "https://api.balldontlie.io/v1"
API_KEY = os.environ.get("BALLDONTLIE_API_KEY")   # read from an environment variable, never hard-coded
DB_FILE = "games.db"
CHART_FILE = "season_chart.png"
JSON_FILE = os.path.join("docs", "data.json")
THROTTLE_SECONDS = 13   # free tier allows 5 requests/minute, so pause between pages


def get_headers():
    """The API needs your key in an Authorization header on every request."""
    if not API_KEY:
        raise SystemExit(
            "No API key found. Set the BALLDONTLIE_API_KEY environment variable.\n"
            "Get a free key at https://app.balldontlie.io"
        )
    return {"Authorization": API_KEY}


def current_season():
    """
    The NBA season starts in October and is labelled by its starting year,
    e.g. the 2025-26 season is season '2025'. This figures that out from today's date.
    """
    today = datetime.date.today()
    return today.year if today.month >= 10 else today.year - 1


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------
def fetch_all_games(season):
    """
    Get every game in the league for this season (no team filter). A full
    season is ~14 pages of 100 games; we sleep between pages to stay under
    the free tier's 5 requests/minute.
    """
    games = []
    cursor = None
    page = 0
    while True:
        params = {"seasons[]": [season], "per_page": 100}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(f"{API_BASE}/games", headers=get_headers(), params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        games.extend(payload["data"])
        page += 1
        print(f"  page {page}: {len(games)} games so far")
        cursor = payload.get("meta", {}).get("next_cursor")
        if not cursor:           # no more pages
            break
        time.sleep(THROTTLE_SECONDS)
    return games


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------
def setup_db(conn):
    """
    Create the table once. game_id is the PRIMARY KEY so each game is stored
    only once. If the database still has the old single-team layout, drop it
    so it can be rebuilt league-wide.
    """
    cols = [row[1] for row in conn.execute("PRAGMA table_info(games)")]
    if cols and "home_team" not in cols:
        conn.execute("DROP TABLE games")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            game_id    INTEGER PRIMARY KEY,
            date       TEXT,
            season     INTEGER,
            home_team  TEXT,
            away_team  TEXT,
            home_score INTEGER,
            away_score INTEGER,
            postseason INTEGER,
            status     TEXT
        )
        """
    )
    conn.commit()


def save_games(conn, games):
    """
    LOAD each finished game. The ON CONFLICT clause means: if we've already
    stored this game, just update it instead of inserting a duplicate. This
    upsert is what makes re-running (and the daily schedule) safe.
    """
    saved = 0
    for g in games:
        if g.get("status") != "Final":
            continue            # game hasn't finished yet, skip it

        conn.execute(
            """
            INSERT INTO games (game_id, date, season, home_team, away_team,
                               home_score, away_score, postseason, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                home_score = excluded.home_score,
                away_score = excluded.away_score,
                postseason = excluded.postseason,
                status     = excluded.status
            """,
            (g["id"], g["date"][:10], g["season"],
             g["home_team"]["full_name"], g["visitor_team"]["full_name"],
             g.get("home_team_score") or 0, g.get("visitor_team_score") or 0,
             1 if g.get("postseason") else 0, g.get("status", "")),
        )
        saved += 1
    conn.commit()
    return saved


# ---------------------------------------------------------------------------
# EXPORT (for the website)
# ---------------------------------------------------------------------------
def export_json(conn, season):
    """Write the data the website reads: every finished game plus the team list."""
    rows = conn.execute(
        """
        SELECT date, home_team, away_team, home_score, away_score, postseason
        FROM games ORDER BY date, game_id
        """
    ).fetchall()
    games = [
        {"date": d, "home": h, "away": a,
         "home_score": hs, "away_score": aws, "postseason": ps}
        for d, h, a, hs, aws, ps in rows
    ]
    teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
    payload = {
        "season": season,
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "teams": teams,
        "games": games,
    }
    os.makedirs(os.path.dirname(JSON_FILE), exist_ok=True)
    with open(JSON_FILE, "w") as f:
        json.dump(payload, f)
    print(f"Saved {JSON_FILE} ({len(teams)} teams, {len(games)} games)")


# ---------------------------------------------------------------------------
# VISUALIZE (the README chart for TEAM_NAME)
# ---------------------------------------------------------------------------
def make_chart(conn, team_name, season):
    """Draw cumulative wins and losses across the season for one team."""
    rows = conn.execute(
        """
        SELECT home_team, home_score, away_score FROM games
        WHERE home_team = ? OR away_team = ?
        ORDER BY date, game_id
        """,
        (team_name, team_name),
    ).fetchall()
    if not rows:
        print("No finished games to chart yet.")
        return

    cum_w = cum_l = 0
    wins, losses = [], []
    for home_team, home_score, away_score in rows:
        if home_team == team_name:
            won = home_score > away_score
        else:
            won = away_score > home_score
        if won:
            cum_w += 1
        else:
            cum_l += 1
        wins.append(cum_w)
        losses.append(cum_l)

    game_numbers = range(1, len(rows) + 1)
    plt.figure(figsize=(10, 5))
    plt.plot(game_numbers, wins, marker="o", markersize=3, label="Wins")
    plt.plot(game_numbers, losses, marker="o", markersize=3, label="Losses")
    plt.title(f"{team_name} — {season}-{str(season + 1)[-2:]} Season")
    plt.xlabel("Game number")
    plt.ylabel("Cumulative total")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(CHART_FILE, dpi=120)
    print(f"Saved {CHART_FILE}. Record so far: {cum_w}-{cum_l}")


def main():
    season = current_season()
    print(f"Fetching all NBA games for the {season}-{season + 1} season...")

    games = fetch_all_games(season)

    conn = sqlite3.connect(DB_FILE)
    setup_db(conn)
    saved = save_games(conn, games)
    print(f"Stored/updated {saved} finished games.")
    export_json(conn, season)
    make_chart(conn, TEAM_NAME, season)
    conn.close()


if __name__ == "__main__":
    main()
