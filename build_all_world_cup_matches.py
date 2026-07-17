#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "pandas",
# ]
# ///
"""
Scrape all World Cup match data from Wikipedia group and knockout articles.

Builds per-team match CSVs in data/ for every team with match data.

Usage:
  ./build_all_world_cup_matches.py
  ./build_all_world_cup_matches.py -v
"""

import csv
import json
import logging
import re
import time
import urllib.request
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from collections import defaultdict
from pathlib import Path

import pandas as pd

PROJECT_DIRECTORY = Path(__file__).resolve().parent
RANKINGS_PATH = PROJECT_DIRECTORY / "data" / "world_cup_rankings.csv"
DATA_DIR = PROJECT_DIRECTORY / "data"

FIFA_TOURNAMENT_SOURCES = {
    1994: "https://www.fifa.com/en/tournaments/mens/worldcup/usa1994",
    1998: "https://www.fifa.com/en/tournaments/mens/worldcup/france1998",
    2002: "https://www.fifa.com/en/tournaments/mens/worldcup/koreajapan2002",
    2006: "https://www.fifa.com/en/tournaments/mens/worldcup/germany2006",
    2010: "https://www.fifa.com/en/tournaments/mens/worldcup/southafrica2010",
    2014: "https://www.fifa.com/en/tournaments/mens/worldcup/brazil2014",
    2018: "https://www.fifa.com/en/tournaments/mens/worldcup/russia2018",
    2022: "https://www.fifa.com/en/tournaments/mens/worldcup/qatar2022",
    2026: "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026",
}

YEARS_CONFIG = {
    1994: {"groups": list("ABCDEF"), "knockout": True},
    1998: {"groups": list("ABCDEFGH"), "knockout": True},
    2002: {"groups": list("ABCDEFGH"), "knockout": True},
    2006: {"groups": list("ABCDEFGH"), "knockout": True},
    2010: {"groups": list("ABCDEFGH"), "knockout": True},
    2014: {"groups": list("ABCDEFGH"), "knockout": True},
    2018: {"groups": list("ABCDEFGH"), "knockout": True},
    2022: {"groups": list("ABCDEFGH"), "knockout": True},
    2026: {
        "groups": list("ABCDEFGHIJKL"),
        "knockout": True,
        "extra": [
            "2026_FIFA_World_Cup_round_of_32",
            "2026_FIFA_World_Cup_knockout_stage",
        ],
    },
}

WIKIPEDIA_API = "https://en.wikipedia.org/w/index.php?title={}&action=raw"


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
    logging.captureWarnings(capture=True)


def parse_args():
    parser = ArgumentParser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="count", default=0, dest="verbose")
    return parser.parse_args()


def fetch_wikipedia(title):
    url = WIKIPEDIA_API.format(title.replace(" ", "_"))
    logging.info("Fetching %s", title)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "WorldCupRankings/1.0 (research project)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8")
    except Exception as exc:
        logging.warning("Failed to fetch %s: %s", title, exc)
        return ""


def parse_fb_code(template):
    """Extract FIFA code from {{fb|CODE}} or {{fb-rt|CODE}} or similar."""
    match = re.search(r"\{\{fb(?:-rt)?\|([A-Z]{3})(?:\|\d+)?\}\}", template)
    if match:
        return match.group(1)
    match = re.search(r"\{\{fbw?\|([A-Z]{3})\}\}", template)
    if match:
        return match.group(1)
    return None


def parse_date(wikitext):
    """Extract date from {{Start date|YYYY|M|D}}."""
    match = re.search(r"\{\{Start date\|(\d{4})\|(\d{1,2})\|(\d{1,2})", wikitext)
    if match:
        y, m, d = match.group(1), match.group(2).zfill(2), match.group(3).zfill(2)
        return f"{y}-{m}-{d}"
    match = re.search(r"date\s*=\s*(\d{4}-\d{2}-\d{2})", wikitext)
    if match:
        return match.group(1)
    return None


def parse_score(text):
    """Parse '2–1' or '1–2' into (goals1, goals2). Handles {{score link|...}} templates."""
    # Find the score line in the template
    score_match = re.search(r"\|\s*score\s*=\s*(.+?)(?:\n\||}}$)", text)
    if not score_match:
        return None, None
    score_text = score_match.group(1)
    # Extract from {{score link|PAGE|SCORE}} — take the last pipe-separated value
    link_match = re.search(r"\{\{score link\|[^|]*\|([^|}]+)", score_text)
    if link_match:
        score_text = link_match.group(1)
    score_text = re.sub(r"\[\[[^\]]+\]\]", "", score_text)
    for sep in ["–", "–", "-"]:
        parts = score_text.strip().split(sep)
        if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
            return int(parts[0].strip()), int(parts[1].strip())
    return None, None


def parse_penalties(wikitext):
    """Extract penalty shootout score."""
    match = re.search(r"penalties1\s*=\s*(\d+).*?penalties2\s*=\s*(\d+)", wikitext, re.DOTALL)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"penaltyscore\s*=\s*(\d+)[––-](\d+)", wikitext)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def parse_aet(wikitext):
    """Check if match went to extra time."""
    if re.search(r"\b(a\.e\.t\.)\b|extra time|golden goal", wikitext, re.IGNORECASE):
        return True
    if re.search(r"aet\s*=\s*yes", wikitext):
        return True
    return False


def parse_team_codes(wikitext):
    """Extract both team FIFA codes from a match template, preserving text order."""
    matches = []

    def add_matches(pattern):
        for m in re.finditer(pattern, wikitext):
            matches.append((m.start(), len(m.group(1)), m.group(1)))

    add_matches(r"\{\{fb(?:-rt)?\|([A-Z]{3})(?:\|\d+)?\}\}")
    add_matches(r"\{\{fb(?:-rt)?\|([A-Z][A-Za-z\s]+)\|")
    add_matches(r"flag\|(?:fb-rt|fb)\|([A-Z]{3})\}\}")
    add_matches(r"fb\|([A-Z]{3})\}\}")
    add_matches(r"\{\{fb(?:-rt)?\|([A-Z]{2,3})\b")

    # Sort by position, then prefer longer matches at same position
    matches.sort(key=lambda x: (x[0], -x[1]))
    seen_codes = set()
    codes = []
    last_pos = -1
    for pos, length, code in matches:
        if code in seen_codes or code.lower() == 'name':
            continue
        if pos == last_pos:
            continue  # skip shorter match at same position
        last_pos = pos
        seen_codes.add(code)
        codes.append(code)
    if len(codes) >= 2:
        return codes[0], codes[1]
    return None, None


CODE_NORMALIZE = {
    "US": "USA",
    "FR Yugoslavia": "YUG",
    "South Africa": "RSA",
    "Saudi Arabia": "KSA",
    "United Arab Emirates": "UAE",
    "Trinidad and Tobago": "TRI",
}


def normalise_code(raw_code):
    return CODE_NORMALIZE.get(raw_code, raw_code)


def determine_stage(section_title, year):
    """Map a section title to a stage name."""
    title_lower = section_title.lower()
    if "third place" in title_lower or "match for third" in title_lower:
        return "Third-place play-off"
    if "final" in title_lower and "semi" not in title_lower and "quarter" not in title_lower:
        return "Final"
    if "semi" in title_lower:
        return "Semi-final"
    if "quarter" in title_lower:
        return "Quarter-final"
    if "round of 16" in title_lower:
        return "Round of 16"
    if "round of 32" in title_lower:
        return "Round of 32"
    if "group" in title_lower:
        return "Group stage"
    return ""


def extract_templates(text, start_marker="{{#invoke:Football box|"):
    """Extract balanced template blocks starting with start_marker."""
    results = []
    idx = 0
    while True:
        start = text.find(start_marker, idx)
        if start == -1:
            break
        # Find matching }} by counting braces
        brace_count = 0
        pos = start
        while pos < len(text):
            if text[pos:pos+2] == "{{":
                brace_count += 1
                pos += 2
            elif text[pos:pos+2] == "}}":
                brace_count -= 1
                if brace_count == 0:
                    # Found matching close
                    results.append(text[start:pos+2])
                    idx = pos + 2
                    break
                pos += 2
            else:
                pos += 1
        else:
            # No matching close found, skip
            idx = start + len(start_marker)
    return results


def parse_matches_from_wikitext(wikitext, year):
    """Parse all match templates and return list of match dicts."""
    matches = []
    current_stage = ""

    # Split by section headers
    sections = re.split(r"\n(={2,6}\s*[^=]+\s*={2,6})\n", wikitext)
    for i in range(1, len(sections), 2):
        header = sections[i]
        content = sections[i + 1] if i + 1 < len(sections) else ""

        title = re.sub(r"^=+\s*|\s*=+$", "", header).strip()
        stage = determine_stage(title, year)
        if stage:
            current_stage = stage
        elif "group" in title.lower():
            current_stage = "Group stage"

        # Try both template formats (case-insensitive)
        for marker in ("{{#invoke:Football box|", "{{Football box", "{{#invoke:football box|"):
            templates = extract_templates(content, marker)
            for match_text in templates:
                team1_code, team2_code = parse_team_codes(match_text)
                if not team1_code or not team2_code:
                    continue
                team1_code = normalise_code(team1_code)
                team2_code = normalise_code(team2_code)

                date = parse_date(match_text)
                g1, g2 = parse_score(match_text)

                pen1, pen2 = parse_penalties(match_text)
                aet = parse_aet(match_text)

                if not date:
                    continue

                stage = current_stage if current_stage else "Group stage"

                matches.append({
                    "year": year,
                    "date": date,
                    "stage": stage,
                    "team1": team1_code,
                    "team2": team2_code,
                    "goals1": g1,
                    "goals2": g2,
                    "penalties1": pen1,
                    "penalties2": pen2,
                    "aet": aet,
                })

    seen = set()
    unique = []
    for m in matches:
        key = (m["date"], m["year"], tuple(sorted([m["team1"], m["team2"]])))
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


def build_team_matches(all_matches, rankings_df):
    """Convert match list to per-team DataFrames."""
    code_to_name = {}
    for _, row in rankings_df.iterrows():
        code_to_name[row["fifa_code"]] = row["team"]

    team_matches = defaultdict(list)

    for m in all_matches:
        t1, t2 = m["team1"], m["team2"]
        g1, g2 = m["goals1"], m["goals2"]
        p1, p2 = m["penalties1"], m["penalties2"]

        if t1 not in code_to_name or t2 not in code_to_name:
            continue

        t1_name = code_to_name[t1]
        t2_name = code_to_name[t2]

        is_completed = g1 is not None and g2 is not None
        result = "completed" if is_completed else "scheduled"

        team_matches[t1].append({
            "world_cup_year": m["year"],
            "match_date": m["date"],
            "stage": m["stage"],
            "opponent_code": t2,
            "opponent": t2_name,
            "team_goals": g1 if g1 is not None else "",
            "opponent_goals": g2 if g2 is not None else "",
            "team_shootout_goals": p1 or "",
            "opponent_shootout_goals": p2 or "",
            "extra_time": str(m["aet"]),
            "status": result,
        })

        team_matches[t2].append({
            "world_cup_year": m["year"],
            "match_date": m["date"],
            "stage": m["stage"],
            "opponent_code": t1,
            "opponent": t1_name,
            "team_goals": g2 if g2 is not None else "",
            "opponent_goals": g1 if g1 is not None else "",
            "team_shootout_goals": p2 or "",
            "opponent_shootout_goals": p1 or "",
            "extra_time": str(m["aet"]),
            "status": result,
        })

    return team_matches, code_to_name


def main(args):
    rankings = pd.read_csv(RANKINGS_PATH)
    all_matches = []

    for year, config in YEARS_CONFIG.items():
        logging.info("=== %d World Cup ===", year)

        # Fetch group articles
        for group in config["groups"]:
            title = f"{year}_FIFA_World_Cup_Group_{group}"
            wikitext = fetch_wikipedia(title)
            if not wikitext:
                continue
            matches = parse_matches_from_wikitext(wikitext, year)
            all_matches.extend(matches)
            logging.info("  Group %s: %d matches", group, len(matches))
            time.sleep(0.5)  # Rate limiting

        # Fetch knockout article
        try:
            title = f"{year}_FIFA_World_Cup_knockout_stage"
            wikitext = fetch_wikipedia(title)
            if wikitext:
                matches = parse_matches_from_wikitext(wikitext, year)
                all_matches.extend(matches)
                logging.info("  Knockout: %d matches", len(matches))
            time.sleep(0.5)
        except Exception:
            pass

        # Fetch extra articles (e.g. 2026 round of 32)
        for extra_title in config.get("extra", []):
            try:
                wikitext = fetch_wikipedia(extra_title)
                if wikitext:
                    matches = parse_matches_from_wikitext(wikitext, year)
                    all_matches.extend(matches)
                    logging.info("  %s: %d matches", extra_title.split("_")[-1], len(matches))
                time.sleep(0.5)
            except Exception:
                pass

    logging.info("Total matches parsed: %d", len(all_matches))

    # Global dedup across articles
    seen = set()
    unique_matches = []
    for m in all_matches:
        key = (m["year"], m["date"], tuple(sorted([m["team1"], m["team2"]])))
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)
    logging.info("After dedup: %d unique matches", len(unique_matches))
    all_matches = unique_matches

    # Build per-team match CSVs
    team_matches, code_to_name = build_team_matches(all_matches, rankings)
    rankings_dict = {}
    for _, row in rankings.iterrows():
        key = (int(row["world_cup_year"]), row["fifa_code"])
        rankings_dict[key] = {
            "fifa_rank": row["fifa_rank"],
            "ranking_date": row["ranking_date"],
            "ranking_source_url": row["ranking_source_url"],
        }

    output_columns = [
        "world_cup_year", "match_date", "stage", "team_rank",
        "team_goals", "opponent_goals", "opponent_code", "opponent",
        "opponent_rank", "opponent_confederation", "result",
        "team_shootout_goals", "opponent_shootout_goals",
        "extra_time", "status", "ranking_date",
        "ranking_source_url", "match_source_url",
    ]

    teams_written = 0
    for code, matches in sorted(team_matches.items()):
        team_name = code_to_name.get(code, code)
        if not matches:
            continue

        try:
            rows = []
            for m in matches:
                year = m["world_cup_year"]
                rk = rankings_dict.get((year, code), {})
                opp_rk = rankings_dict.get((year, m["opponent_code"]), {})
                opp_confed = ""
                for _, row in rankings.iterrows():
                    if row["fifa_code"] == m["opponent_code"] and int(row["world_cup_year"]) == year:
                        opp_confed = row["confederation"]
                        break

                goals_for = m["team_goals"]
                goals_against = m["opponent_goals"]

                if m["status"] == "completed":
                    if m["team_shootout_goals"]:
                        result = "win" if int(m["team_shootout_goals"]) > int(m["opponent_shootout_goals"]) else "loss"
                    elif isinstance(goals_for, int) and isinstance(goals_against, int):
                        if goals_for > goals_against:
                            result = "win"
                        elif goals_for < goals_against:
                            result = "loss"
                        else:
                            result = "draw"
                    else:
                        result = "draw"
                else:
                    result = "scheduled"

                rows.append({
                    "world_cup_year": year,
                    "match_date": m["match_date"],
                    "stage": m["stage"],
                    "team_rank": rk.get("fifa_rank", ""),
                    "team_goals": goals_for,
                    "opponent_goals": goals_against,
                    "opponent_code": m["opponent_code"],
                    "opponent": m["opponent"],
                    "opponent_rank": opp_rk.get("fifa_rank", ""),
                    "opponent_confederation": opp_confed,
                    "result": result,
                    "team_shootout_goals": m["team_shootout_goals"],
                    "opponent_shootout_goals": m["opponent_shootout_goals"],
                    "extra_time": m["extra_time"],
                    "status": m["status"],
                    "ranking_date": rk.get("ranking_date", ""),
                    "ranking_source_url": rk.get("ranking_source_url", ""),
                    "match_source_url": FIFA_TOURNAMENT_SOURCES.get(year, ""),
                })

            df = pd.DataFrame(rows)
            df = df[output_columns].sort_values(["world_cup_year", "match_date"])

            safe_prefix = team_name.lower().replace(" ", "_")
            path = DATA_DIR / f"{safe_prefix}_world_cup_matches.csv"
            df.to_csv(path, index=False)
            teams_written += 1
            logging.info("Wrote %s (%d matches)", path.name, len(df))
        except Exception as exc:
            logging.warning("Failed for %s (%s): %s", code, team_name, exc)

    logging.info("Done — %d team match CSVs written", teams_written)


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
