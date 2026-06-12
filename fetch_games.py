"""
NBA Stats Tracker
-----------------
A small data pipeline (ETL) that:
  1. EXTRACT  - pulls your team's games for the current season from the
                BALLDONTLIE API.
  2. TRANSFORM - turns the raw API response into clean rows (opponent,
                scores, win/loss).
  3. LOAD     - stores them in a SQLite database without creating
                duplicates, so re-running is always safe.
Then it draws a chart of your team's season so far.

Run it by hand with:   python fetch_games.py
GitHub Actions runs it on a schedule (see .github/workflows/update.yml).
"""

import os
import datetime
import sqlite3

import requests
import matplotlib
matplotlib.use("Agg")          # lets matplotlib draw without a screen (needed on GitHub)
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Settings  --  change TEAM_NAME to the team you follow.
# ---------------------------------------------------------------------------
TEAM_NAME = "Los Angeles Lakers"
API_BASE = "https://api.balldontlie.io/v1"
API_KEY = os.environ.get("BALLDONTLIE_API_KEY")   # read from an environment variable, never hard-coded
DB_FILE = "games.db"
CHART_FILE = "season_chart.png"


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
def find_team_id(name):
    """Look up the numeric team id the API uses, from the team's name."""
    resp = requests.get(f"{API_BASE}/teams", headers=get_headers(), timeout=30)
    resp.raise_for_status()
    teams = resp.json()["data"]
    for t in teams:
        if name.lower() == t["full_name"].lower():
            return t["id"]
    # looser match if the exact name wasn't found (e.g. "Celtics")
    for t in teams:
        if name.lower() in t["full_name"].lower():
            return t["id"]
    raise SystemExit(f"Could not find a team matching '{name}'.")


def fetch_games(team_id, season):
    """Get every game for this team this season. Handles the API's paging for you."""
    games = []
    cursor = None
    while True:
        params = {"seasons[]": [season], "team_ids[]": [team_id], "per_page": 100}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(f"{API_BASE}/games", headers=get_headers(), params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        games.extend(payload["data"])
        cursor = payload.get("meta", {}).get("next_cursor")
        if not cursor:           # no more pages
            break
    return games


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------
def setup_db(conn):
    """Create the table once. game_id is the PRIMARY KEY so each game is stored only once."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            game_id    INTEGER PRIMARY KEY,
            date       TEXT,
            season     INTEGER,
            opponent   TEXT,
            home_away  TEXT,
            team_score INTEGER,
            opp_score  INTEGER,
            result     TEXT,
            status     TEXT
        )
        """
    )
    conn.commit()


def save_games(conn, games, team_id):
    """
    TRANSFORM each raw game into our clean shape, then LOAD it.
    The ON CONFLICT clause means: if we've already stored this game, just update
    the scores instead of inserting a duplicate. This is what makes re-running safe.
    """
    saved = 0
    for g in games:
        home, away = g["home_team"], g["visitor_team"]
        home_score = g.get("home_team_score") or 0
        away_score = g.get("visitor_team_score") or 0

        if home_score == 0 and away_score == 0:
            continue            # game hasn't been played yet, skip it

        if home["id"] == team_id:
            home_away, opponent = "Home", away["full_name"]
            team_score, opp_score = home_score, away_score
        else:
            home_away, opponent = "Away", home["full_name"]
            team_score, opp_score = away_score, home_score

        result = "W" if team_score > opp_score else "L"

        conn.execute(
            """
            INSERT INTO games (game_id, date, season, opponent, home_away,
                               team_score, opp_score, result, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                team_score = excluded.team_score,
                opp_score  = excluded.opp_score,
                result     = excluded.result,
                status     = excluded.status
            """,
            (g["id"], g["date"][:10], g["season"], opponent, home_away,
             team_score, opp_score, result, g.get("status", "")),
        )
        saved += 1
    conn.commit()
    return saved


# ---------------------------------------------------------------------------
# VISUALIZE
# ---------------------------------------------------------------------------
def make_chart(conn, team_name, season):
    """Draw cumulative wins and losses across the season."""
    rows = conn.execute("SELECT date, result FROM games ORDER BY date").fetchall()
    if not rows:
        print("No finished games to chart yet.")
        return

    cum_w = cum_l = 0
    wins, losses = [], []
    for _date, result in rows:
        if result == "W":
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
    print(f"Tracking {TEAM_NAME} for the {season}-{season + 1} season...")

    team_id = find_team_id(TEAM_NAME)
    games = fetch_games(team_id, season)

    conn = sqlite3.connect(DB_FILE)
    setup_db(conn)
    saved = save_games(conn, games, team_id)
    print(f"Stored/updated {saved} finished games.")
    make_chart(conn, TEAM_NAME, season)
    conn.close()


if __name__ == "__main__":
    main()
