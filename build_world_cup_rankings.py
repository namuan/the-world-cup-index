#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas",
#   "persistent-cache@git+https://github.com/namuan/persistent-cache"
# ]
# ///
"""Build a tidy dataset of pre-tournament FIFA ranks for World Cup teams.

The source pages are pinned Wikipedia revisions whose qualified-team lists cite
the corresponding official FIFA ranking release.

Usage:
./build_world_cup_rankings.py -h
./build_world_cup_rankings.py
./build_world_cup_rankings.py --refresh -v
./build_world_cup_rankings.py -vv
"""

from __future__ import annotations

import json
import logging
import re
import time
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from persistent_cache.core import PersistentCache


ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw" / "wikipedia"
DEFAULT_OUTPUT = ROOT / "data" / "world_cup_rankings.csv"
DEFAULT_SOURCES_OUTPUT = ROOT / "data" / "world_cup_ranking_sources.csv"
USER_AGENT = "england-world-cup-rankings/1.0 (public data research)"
CACHE_DIR = ROOT / ".cache" / "world-cup-rankings"


@dataclass(frozen=True)
class Tournament:
    year: int
    ranking_date: str
    expected_teams: int
    revision_id: int
    start_marker: str
    ranking_source_url: str

    @property
    def page_title(self) -> str:
        return f"{self.year} FIFA World Cup"

    @property
    def source_page_url(self) -> str:
        title = self.page_title.replace(" ", "_")
        return (
            f"https://en.wikipedia.org/w/index.php?title={title}"
            f"&oldid={self.revision_id}"
        )


TOURNAMENTS = (
    Tournament(
        1994,
        "1994-06-14",
        24,
        1364407895,
        "following 24 teams qualified for the tournament",
        "https://www.fifa.com/fifa-world-ranking/men?dateId=id11",
    ),
    Tournament(
        1998,
        "1998-05-20",
        32,
        1364001590,
        "following 32 teams, shown with final pre-tournament rankings",
        "https://web.archive.org/web/20160222025820/"
        "http://www.fifa.com/fifa-world-ranking/ranking-table/men/rank=50/index.html",
    ),
    Tournament(
        2002,
        "2002-05-15",
        32,
        1364572375,
        "following 32 teams, shown with final pre-tournament rankings",
        "https://web.archive.org/web/20151026211858/"
        "http://www.fifa.com/fifa-world-ranking/ranking-table/men/rank=97/index.html",
    ),
    Tournament(
        2006,
        "2006-05-17",
        32,
        1364371717,
        "following 32 teams, shown with final pre-tournament rankings",
        "https://inside.fifa.com/fifa-world-ranking",
    ),
    Tournament(
        2010,
        "2010-05-26",
        32,
        1363928575,
        "following 32 teams, shown with final pre-tournament rankings",
        "https://web.archive.org/web/20191006015211/"
        "https://www.fifa.com/fifa-world-ranking/ranking-table/men/rank/id9054/",
    ),
    Tournament(
        2014,
        "2014-06-05",
        32,
        1363796172,
        "the following 32 teams – shown with their last pre-tournament",
        "https://web.archive.org/web/20141107005059/"
        "http://www.fifa.com/fifa-world-ranking/ranking-table/men/rank=239/index.html",
    ),
    Tournament(
        2018,
        "2018-06-07",
        32,
        1364201186,
        "====Qualified teams====",
        "https://inside.fifa.com/tournaments/mens/worldcup/2018russia/news/"
        "calculating-russia-2018-s-toughest-groups",
    ),
    Tournament(
        2022,
        "2022-10-06",
        32,
        1364125908,
        "qualified teams, listed by region, with numbers in parentheses "
        "indicating final positions",
        "https://www.fifa.com/fifa-world-ranking/mens-ranking?dateId=id13792",
    ),
    Tournament(
        2026,
        "2026-06-11",
        48,
        1364564584,
        "qualified teams, listed by region, with numbers in parentheses "
        "indicating final positions",
        "https://inside.fifa.com/fifa-world-ranking/men?dateId=id11944",
    ),
)


# Consistent FIFA-style display names. Historical teams retain their historical
# identity; selected current names follow FIFA's spelling.
TEAM_NAMES = {
    "ALG": "Algeria",
    "ANG": "Angola",
    "ARG": "Argentina",
    "AUS": "Australia",
    "AUT": "Austria",
    "BEL": "Belgium",
    "BIH": "Bosnia and Herzegovina",
    "BOL": "Bolivia",
    "BRA": "Brazil",
    "BUL": "Bulgaria",
    "CAN": "Canada",
    "CHI": "Chile",
    "CHN": "China PR",
    "CIV": "Côte d'Ivoire",
    "CMR": "Cameroon",
    "COD": "Congo DR",
    "COL": "Colombia",
    "CPV": "Cabo Verde",
    "CRC": "Costa Rica",
    "CRO": "Croatia",
    "CUW": "Curaçao",
    "CZE": "Czechia",
    "DEN": "Denmark",
    "ECU": "Ecuador",
    "EGY": "Egypt",
    "ENG": "England",
    "ESP": "Spain",
    "FRA": "France",
    "GER": "Germany",
    "GHA": "Ghana",
    "GRE": "Greece",
    "HAI": "Haiti",
    "HON": "Honduras",
    "IRL": "Republic of Ireland",
    "IRN": "IR Iran",
    "IRQ": "Iraq",
    "ISL": "Iceland",
    "ITA": "Italy",
    "JAM": "Jamaica",
    "JOR": "Jordan",
    "JPN": "Japan",
    "KOR": "Korea Republic",
    "KSA": "Saudi Arabia",
    "MAR": "Morocco",
    "MEX": "Mexico",
    "NED": "Netherlands",
    "NGA": "Nigeria",
    "NOR": "Norway",
    "NZL": "New Zealand",
    "PAN": "Panama",
    "PAR": "Paraguay",
    "PER": "Peru",
    "POL": "Poland",
    "POR": "Portugal",
    "PRK": "Korea DPR",
    "QAT": "Qatar",
    "ROU": "Romania",
    "RSA": "South Africa",
    "RUS": "Russia",
    "SCG": "Serbia and Montenegro",
    "SCO": "Scotland",
    "SEN": "Senegal",
    "SRB": "Serbia",
    "SUI": "Switzerland",
    "SVK": "Slovakia",
    "SVN": "Slovenia",
    "SWE": "Sweden",
    "TOG": "Togo",
    "TRI": "Trinidad and Tobago",
    "TUN": "Tunisia",
    "TUR": "Türkiye",
    "UKR": "Ukraine",
    "URU": "Uruguay",
    "USA": "USA",
    "UZB": "Uzbekistan",
    "WAL": "Wales",
    "YUG": "FR Yugoslavia",
}

YEAR_NAME_OVERRIDES = {
    (2006, "CZE"): "Czech Republic",
    (2002, "TUR"): "Turkey",
}

CODE_ALIASES = {
    "FRY": "YUG",  # Wikipedia flag code; FIFA used YUG for FR Yugoslavia.
    "SAU": "KSA",  # Historical flag-template alias.
}

CONFEDERATIONS = ("AFC", "CAF", "CONCACAF", "CONMEBOL", "OFC", "UEFA")
TEAM_PATTERNS = (
    re.compile(r"\{\{fb\|([^|}\n]+)"),
    re.compile(r"\{\{#invoke:flagg\|main\|unpe\|avar=fb\|([^|}\n]+)"),
    re.compile(r"\{\{#invoke:flag\|fb\|([^|}\n]+)"),
    re.compile(r"\{\{flagdeco\|([^|}\n]+)"),
)
RANK_PATTERN = re.compile(r"\((?:joint\s+)?(\d+)\)", re.IGNORECASE)


def setup_logging(verbosity):
    logging_level = logging.WARNING
    if verbosity == 1:
        logging_level = logging.INFO
    elif verbosity >= 2:
        logging_level = logging.DEBUG

    logging.basicConfig(
        handlers=[
            logging.StreamHandler(),
        ],
        format="%(asctime)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging_level,
    )
    logging.captureWarnings(capture=True)


def parse_args():
    parser = ArgumentParser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        dest="verbose",
        help="Increase verbosity of logging output",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-download pinned source revisions instead of using raw files",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sources-output", type=Path, default=DEFAULT_SOURCES_OUTPUT)
    return parser.parse_args()


@PersistentCache(cache_dir=str(CACHE_DIR))
def download_source(revision_id: int, refresh_token: int | None = None) -> dict:
    # refresh_token intentionally participates in the persistent cache key.
    del refresh_token
    query = urlencode(
        {
            "action": "parse",
            "oldid": revision_id,
            "prop": "wikitext|revid",
            "format": "json",
            "formatversion": 2,
        }
    )
    request = Request(
        f"https://en.wikipedia.org/w/api.php?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(
            f"source download failed for revision {revision_id}: {payload['error']}"
        )
    return payload


def load_source(tournament: Tournament, refresh: bool) -> dict:
    path = RAW_DIR / f"{tournament.year}.json"
    if refresh or not path.exists():
        logging.info("Downloading pinned source for %s", tournament.year)
        refresh_token = time.time_ns() if refresh else None
        payload = download_source(tournament.revision_id, refresh_token)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        logging.debug("Using cached raw source for %s", tournament.year)
        payload = json.loads(path.read_text(encoding="utf-8"))

    parsed = payload.get("parse", {})
    actual_revision = parsed.get("revid")
    if actual_revision != tournament.revision_id:
        raise ValueError(
            f"{tournament.year}: expected revision {tournament.revision_id}, "
            f"got {actual_revision}"
        )
    return payload


def extract_block(wikitext: str, tournament: Tournament) -> str:
    start = wikitext.lower().find(tournament.start_marker.lower())
    if start < 0:
        raise ValueError(f"{tournament.year}: qualified-team section not found")
    possible_ends = (
        wikitext.find("{{col-end}}", start),
        wikitext.find("{{col end}}", start),
    )
    ends = [position for position in possible_ends if position >= 0]
    if not ends:
        raise ValueError(f"{tournament.year}: end of qualified-team section not found")
    return wikitext[start : min(ends)]


def extract_team_code(line: str) -> str | None:
    for pattern in TEAM_PATTERNS:
        match = pattern.search(line)
        if match:
            raw_code = match.group(1).strip()
            return CODE_ALIASES.get(raw_code, raw_code)
    return None


def extract_rows(payload: dict, tournament: Tournament) -> list[dict[str, object]]:
    wikitext = payload["parse"]["wikitext"]
    block = extract_block(wikitext, tournament)
    rows: list[dict[str, object]] = []
    confederation: str | None = None

    for line in block.splitlines():
        confederation_match = re.search(
            r"\|(AFC|CAF|CONCACAF|CONMEBOL|OFC|UEFA)\]\]", line
        )
        if confederation_match:
            confederation = confederation_match.group(1)
        if not line.startswith("*"):
            continue

        code = extract_team_code(line)
        ranks = RANK_PATTERN.findall(line)
        if code is None or not ranks:
            continue
        if confederation is None:
            raise ValueError(f"{tournament.year}: no confederation for {line!r}")
        if code not in TEAM_NAMES:
            raise ValueError(f"{tournament.year}: unknown team code {code!r}")

        rows.append(
            {
                "world_cup_year": tournament.year,
                "ranking_date": tournament.ranking_date,
                "fifa_code": code,
                "team": YEAR_NAME_OVERRIDES.get(
                    (tournament.year, code), TEAM_NAMES[code]
                ),
                "confederation": confederation,
                "fifa_rank": int(ranks[-1]),
                "source_revision_id": tournament.revision_id,
                "source_url": tournament.source_page_url,
                "ranking_source_url": tournament.ranking_source_url,
            }
        )

    validate_tournament_rows(rows, tournament)
    return rows


def validate_tournament_rows(
    rows: list[dict[str, object]], tournament: Tournament
) -> None:
    if len(rows) != tournament.expected_teams:
        raise ValueError(
            f"{tournament.year}: expected {tournament.expected_teams} teams, "
            f"extracted {len(rows)}"
        )
    codes = [str(row["fifa_code"]) for row in rows]
    if len(codes) != len(set(codes)):
        duplicates = sorted(code for code in set(codes) if codes.count(code) > 1)
        raise ValueError(f"{tournament.year}: duplicate team codes {duplicates}")
    invalid_confederations = sorted(
        {
            str(row["confederation"])
            for row in rows
            if row["confederation"] not in CONFEDERATIONS
        }
    )
    if invalid_confederations:
        raise ValueError(
            f"{tournament.year}: invalid confederations {invalid_confederations}"
        )
    invalid_ranks = [row["fifa_rank"] for row in rows if int(row["fifa_rank"]) < 1]
    if invalid_ranks:
        raise ValueError(f"{tournament.year}: invalid ranks {invalid_ranks}")


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=fieldnames)
    frame.to_csv(path, index=False)


def validate_complete_dataset(rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(rows)
    expected_counts = {
        tournament.year: tournament.expected_teams for tournament in TOURNAMENTS
    }
    actual_counts = frame.groupby("world_cup_year").size().to_dict()
    if actual_counts != expected_counts:
        raise ValueError(
            f"unexpected tournament counts: expected {expected_counts}, got {actual_counts}"
        )
    if frame.duplicated(["world_cup_year", "fifa_code"]).any():
        duplicates = frame.loc[
            frame.duplicated(["world_cup_year", "fifa_code"], keep=False),
            ["world_cup_year", "fifa_code"],
        ]
        raise ValueError(f"duplicate tournament teams:\n{duplicates.to_string(index=False)}")


def main(args) -> int:
    logging.debug("Arguments: %s", args)
    all_rows: list[dict[str, object]] = []
    source_rows: list[dict[str, object]] = []

    for tournament in TOURNAMENTS:
        payload = load_source(tournament, args.refresh)
        rows = extract_rows(payload, tournament)
        logging.info("Validated %s teams for %s", len(rows), tournament.year)
        all_rows.extend(rows)
        source_rows.append(
            {
                "world_cup_year": tournament.year,
                "ranking_date": tournament.ranking_date,
                "team_count": len(rows),
                "source_revision_id": tournament.revision_id,
                "source_url": tournament.source_page_url,
                "ranking_source_url": tournament.ranking_source_url,
            }
        )

    all_rows.sort(
        key=lambda row: (
            int(row["world_cup_year"]),
            int(row["fifa_rank"]),
            str(row["team"]),
        )
    )
    expected_total = sum(tournament.expected_teams for tournament in TOURNAMENTS)
    if len(all_rows) != expected_total:
        raise ValueError(f"expected {expected_total} total rows, got {len(all_rows)}")
    validate_complete_dataset(all_rows)

    fields = [
        "world_cup_year",
        "ranking_date",
        "fifa_code",
        "team",
        "confederation",
        "fifa_rank",
        "source_revision_id",
        "source_url",
        "ranking_source_url",
    ]
    write_csv(args.output, all_rows, fields)
    write_csv(
        args.sources_output,
        source_rows,
        [
            "world_cup_year",
            "ranking_date",
            "team_count",
            "source_revision_id",
            "source_url",
            "ranking_source_url",
        ],
    )
    print(f"Wrote {len(all_rows)} rows to {args.output}")
    print(f"Wrote {len(source_rows)} source records to {args.sources_output}")
    return 0


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    try:
        raise SystemExit(main(args))
    except (OSError, RuntimeError, ValueError) as error:
        logging.error("%s", error)
        raise SystemExit(1)
