#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = []
# ///
"""
Build an SQLite database from all World Cup rankings and match CSVs.

Usage:
  ./build_database.py
  ./build_database.py --db worldcup.db -v
"""

import csv
import logging
import sqlite3
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from pathlib import Path

PROJECT_DIRECTORY = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIRECTORY / "data"
RANKINGS_PATH = DATA_DIR / "world_cup_rankings.csv"


def setup_logging(verbosity):
    logging_level = logging.WARNING
    if verbosity == 1:
        logging_level = logging.INFO
    elif verbosity >= 2:
        logging_level = logging.DEBUG
    logging.basicConfig(
        handlers=[logging.StreamHandler()],
        format="%(asctime)s - %(message)s",
        datefmt="%H:%M:%S",
        level=logging_level,
    )


def parse_args():
    parser = ArgumentParser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="worldcup.db", type=Path, help="Database path (default: %(default)s)")
    parser.add_argument("-v", "--verbose", action="count", default=0, dest="verbose")
    return parser.parse_args()


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(args):
    db_path = args.db
    if not db_path.is_absolute():
        db_path = PROJECT_DIRECTORY / db_path
    db_path.unlink(missing_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # ── rankings ──────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE rankings (
            world_cup_year INTEGER NOT NULL,
            ranking_date   TEXT    NOT NULL,
            fifa_code      TEXT    NOT NULL,
            team           TEXT    NOT NULL,
            confederation  TEXT    NOT NULL,
            fifa_rank      INTEGER NOT NULL,
            source_url     TEXT    NOT NULL,
            PRIMARY KEY (world_cup_year, fifa_code)
        )
    """)

    rankings = read_csv(RANKINGS_PATH)
    conn.executemany(
        """INSERT INTO rankings (world_cup_year, ranking_date, fifa_code, team,
           confederation, fifa_rank, source_url)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (int(r["world_cup_year"]), r["ranking_date"], r["fifa_code"],
             r["team"], r["confederation"], int(r["fifa_rank"]),
             r["ranking_source_url"])
            for r in rankings
        ],
    )
    logging.info("Inserted %d rankings", len(rankings))

    # ── team code lookup (filename → fifa_code) ──────────────
    code_by_name = {}
    for r in rankings:
        key = r["team"].lower().replace(" ", "_")
        if key not in code_by_name:
            code_by_name[key] = r["fifa_code"]

    # ── matches ───────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE matches (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            world_cup_year          INTEGER NOT NULL,
            match_date              TEXT    NOT NULL,
            stage                   TEXT    NOT NULL,
            team_code               TEXT    NOT NULL,
            team_rank               INTEGER,
            team_goals              INTEGER,
            opponent_goals          INTEGER,
            opponent_code           TEXT    NOT NULL,
            opponent                TEXT    NOT NULL,
            opponent_rank           INTEGER,
            opponent_confederation  TEXT    NOT NULL,
            result                  TEXT    NOT NULL,
            team_shootout_goals     INTEGER,
            opponent_shootout_goals INTEGER,
            extra_time              INTEGER NOT NULL DEFAULT 0,
            status                  TEXT    NOT NULL,
            ranking_date            TEXT    NOT NULL,
            match_source_url        TEXT    NOT NULL,
            FOREIGN KEY (world_cup_year, team_code)
                REFERENCES rankings(world_cup_year, fifa_code),
            FOREIGN KEY (world_cup_year, opponent_code)
                REFERENCES rankings(world_cup_year, fifa_code)
        )
    """)

    total_matches = 0
    for path in sorted(DATA_DIR.glob("*_world_cup_matches.csv")):
        stem = path.stem.replace("_world_cup_matches", "")
        team_code = code_by_name.get(stem)
        if not team_code:
            logging.warning("No FIFA code for %s", stem)
            continue

        matches = read_csv(path)
        rows = []
        for m in matches:
            tg = m.get("team_goals", "")
            og = m.get("opponent_goals", "")
            ts = m.get("team_shootout_goals", "")
            os = m.get("opponent_shootout_goals", "")
            tr = m.get("team_rank", "")
            or_ = m.get("opponent_rank", "")

            rows.append((
                int(m["world_cup_year"]),
                m["match_date"],
                m.get("stage", "Group stage"),
                team_code,
                int(tr) if tr else None,
                int(tg) if tg else None,
                int(og) if og else None,
                m["opponent_code"],
                m.get("opponent", ""),
                int(or_) if or_ else None,
                m.get("opponent_confederation", ""),
                m["result"],
                int(ts) if ts else None,
                int(os) if os else None,
                1 if str(m.get("extra_time", "")).lower() == "true" else 0,
                m["status"],
                m.get("ranking_date", ""),
                m.get("match_source_url", ""),
            ))

        conn.executemany(
            """INSERT INTO matches (world_cup_year, match_date, stage,
               team_code, team_rank, team_goals, opponent_goals,
               opponent_code, opponent, opponent_rank,
               opponent_confederation, result, team_shootout_goals,
               opponent_shootout_goals, extra_time, status,
               ranking_date, match_source_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        total_matches += len(rows)
        logging.info("  %s: %d matches", path.name, len(rows))

    # ── indexes ───────────────────────────────────────────────
    conn.execute("CREATE INDEX idx_rankings_code ON rankings(fifa_code)")
    conn.execute("CREATE INDEX idx_rankings_year ON rankings(world_cup_year)")
    conn.execute("CREATE INDEX idx_matches_team ON matches(team_code)")
    conn.execute("CREATE INDEX idx_matches_opponent ON matches(opponent_code)")
    conn.execute("CREATE INDEX idx_matches_year ON matches(world_cup_year)")
    conn.execute("CREATE INDEX idx_matches_date ON matches(match_date)")

    conn.commit()
    conn.close()
    logging.info("Wrote %s: %d rankings, %d matches", db_path, len(rankings), total_matches)


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
