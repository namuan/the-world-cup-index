#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = []
# ///
"""
Generate a static HTML report for every team in the World Cup rankings.

For teams with match data (data/<team>_world_cup_matches.csv), fixtures are shown.
For teams without match data, a ranking-only report is generated.

Usage:
  ./generate_all_reports.py
  ./generate_all_reports.py --output-dir reports
"""

import csv
import html
import logging
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from textwrap import dedent

PROJECT_DIRECTORY = Path(__file__).resolve().parent
RANKINGS_PATH = PROJECT_DIRECTORY / "data" / "world_cup_rankings.csv"
DATA_DIR = PROJECT_DIRECTORY / "data"

EXCLUDE_CODES = {"fifa_code"}


def setup_logging(verbosity):
    logging_level = logging.WARNING
    if verbosity == 1:
        logging_level = logging.INFO
    elif verbosity >= 2:
        logging_level = logging.DEBUG
    logging.basicConfig(
        handlers=[logging.StreamHandler()],
        format="%(asctime)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging_level,
    )
    logging.captureWarnings(capture=True)


def parse_args():
    parser = ArgumentParser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output-dir",
        default="docs",
        type=Path,
        help="Output directory (default: %(default)s)",
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, dest="verbose",
        help="Increase verbosity",
    )
    return parser.parse_args()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def read_csv_if_exists(path):
    if path.exists():
        return read_csv(path)
    return []


def discover_teams(rankings):
    teams = {}
    for row in rankings:
        code = row["fifa_code"]
        if code in EXCLUDE_CODES:
            continue
        if code not in teams:
            teams[code] = {
                "name": row["team"],
                "field_prefix": row["team"].lower().replace(" ", "_"),
                "csv_prefix": row["team"].lower().replace(" ", "_"),
            }
    return teams


def normalize_fields(matches, prefix):
    team_rank = f"{prefix}_rank"
    team_goals = f"{prefix}_goals"
    team_shootout = f"{prefix}_shootout_goals"
    for m in matches:
        if team_rank in m:
            m["team_rank"] = m.pop(team_rank)
        if team_goals in m:
            m["team_goals"] = m.pop(team_goals)
        if team_shootout in m:
            m["team_shootout_goals"] = m.pop(team_shootout)
    return matches


def load_matches(team_info):
    prefix = team_info["field_prefix"]
    path = DATA_DIR / f"{prefix}_world_cup_matches.csv"
    matches = read_csv_if_exists(path)
    return normalize_fields(matches, prefix)


def format_date(iso_date, include_year=True):
    parsed = datetime.strptime(iso_date, "%Y-%m-%d")
    month = parsed.strftime("%b")
    return f"{parsed.day} {month} {parsed.year}" if include_year else f"{parsed.day} {month}"


def score_value(value):
    return value if value else "—"


def outcome_note(m):
    if m["status"] == "scheduled":
        return f"Scheduled · {format_date(m['match_date'])}"
    if m.get("team_shootout_goals"):
        verb = "Won" if m["result"] == "win" else "Lost"
        return f"{verb} {m['team_shootout_goals']}–{m['opponent_shootout_goals']} on penalties"
    if m["extra_time"].lower() == "true":
        return "After extra time"
    return "Full time"


def reached_label(year, matches, team_name):
    if not matches:
        return "Did not qualify"
    scheduled = next((m for m in matches if m["status"] == "scheduled"), None)
    if scheduled:
        return scheduled["stage"]
    if year == 1998 and team_name in ("France",):
        return "Winners"
    if year == 2006 and team_name in ("France",):
        return "Runners-up"
    if year == 2018 and team_name in ("France",):
        return "Winners"
    if year == 2022 and team_name in ("France",):
        return "Runners-up"
    return matches[-1]["stage"]


def summary_for(year, matches, team_name):
    completed = [m for m in matches if m["status"] == "completed"]
    wins = sum(m["result"] == "win" for m in completed)
    draws = sum(m["result"] == "draw" for m in completed)
    losses = sum(m["result"] == "loss" for m in completed)
    goals_for = sum(int(m["team_goals"]) for m in completed)
    goals_against = sum(int(m["opponent_goals"]) for m in completed)
    return {
        "played": len(completed),
        "record": f"{wins}W · {draws}D · {losses}L" if completed else "—",
        "goals": f"{goals_for}–{goals_against}" if completed else "—",
        "reached": reached_label(year, matches, team_name),
    }


def rank_comparison(m, team_name):
    team_rank = int(m["team_rank"])
    opp_rank = int(m["opponent_rank"])
    difference = abs(team_rank - opp_rank)
    if difference == 0:
        return "Level in the ranking"
    subject = team_name if team_rank < opp_rank else m["opponent"]
    places = "place" if difference == 1 else "places"
    return f"{subject} {difference} {places} higher"


def match_markup(m, index, team_name):
    result_label = {"win": "Win", "draw": "Draw", "loss": "Loss", "scheduled": "Next"}[m["result"]]
    return dedent(
        f"""
        <article class="fixture result-{html.escape(m['result'])}" aria-label="{html.escape(m['stage'])}: {html.escape(team_name)} against {html.escape(m['opponent'])}">
          <span class="fixture-number">{index:02d}</span>
          <div class="fixture-meta">
            <strong>{html.escape(m['stage'])}</strong>
            <time datetime="{html.escape(m['match_date'])}">{format_date(m['match_date'])}</time>
          </div>
          <div class="fixture-score">
            <div class="side england-side">
              <span>{html.escape(team_name)}</span>
              <small>FIFA #{html.escape(m['team_rank'])}</small>
            </div>
            <strong>{score_value(m['team_goals'])}</strong>
            <i aria-hidden="true">—</i>
            <strong>{score_value(m['opponent_goals'])}</strong>
            <div class="side opponent-side">
              <span>{html.escape(m['opponent'])}</span>
              <small>FIFA #{html.escape(m['opponent_rank'])}</small>
            </div>
          </div>
          <div class="fixture-outcome">
            <b>{result_label}</b>
            <span>{html.escape(outcome_note(m))}</span>
            <small>{html.escape(rank_comparison(m, team_name))}</small>
          </div>
        </article>
        """
    ).strip()


def no_match_note(year, team_name, has_ranking):
    if year == 1994 and not has_ranking:
        return (
            f"{team_name} did not qualify for the 1994 World Cup, "
            f"so there is no pre-tournament {team_name} rank or match ledger."
        )
    if not has_ranking:
        return f"{team_name} did not qualify for the {year} World Cup."
    return f"No match data available for the {year} World Cup."


def tournament_markup(year, ranking, matches, tournament_ranking, team_name):
    summary = summary_for(year, matches, team_name)
    rank_display = f"#{html.escape(ranking['fifa_rank'])}" if ranking else "DNQ"

    if matches:
        fixtures = "\n".join(match_markup(m, i, team_name) for i, m in enumerate(matches, 1))
    else:
        label = no_match_note(year, team_name, has_ranking=ranking is not None)
        fixtures = dedent(
            f"""
            <div class="dnq-note">
              <strong>No {html.escape(team_name)} matches</strong>
              <p>{html.escape(label)}</p>
            </div>
            """
        ).strip()

    match_source = matches[0]["match_source_url"] if matches else ""
    ranking_source = (
        ranking["ranking_source_url"] if ranking else tournament_ranking["ranking_source_url"]
    )
    return dedent(
        f"""
        <section class="tournament" id="world-cup-{year}" aria-label="World Cup {year}">
          <dl class="tournament-facts" aria-label="{html.escape(team_name)} World Cup {year} summary">
            <div class="tournament-year"><dt>Year</dt><dd>{year}</dd></div>
            <div class="tournament-rank"><dt>Rank</dt><dd>{rank_display}</dd></div>
            <div><dt>Played</dt><dd>{summary['played']}</dd></div>
            <div><dt>Results</dt><dd>{summary['record']}</dd></div>
            <div><dt>Goals</dt><dd>{summary['goals']}</dd></div>
            <div><dt>Reached</dt><dd>{html.escape(summary['reached'])}</dd></div>
          </dl>

          <div class="fixtures">
            {fixtures}
          </div>

          <footer class="tournament-sources">
            <a href="{html.escape(match_source)}">FIFA tournament record ↗</a>
            <a href="{html.escape(ranking_source)}">Ranking source ↗</a>
            <a href="#report-top">Back to year index ↑</a>
          </footer>
        </section>
        """
    ).strip()


def build_report(rankings, matches, team_info, fifa_code):
    team_name = team_info["name"]
    years = sorted({int(row["world_cup_year"]) for row in rankings})
    team_rankings = {
        int(row["world_cup_year"]): row for row in rankings if row["fifa_code"] == fifa_code
    }
    tournament_rankings = {}
    for row in rankings:
        tournament_rankings.setdefault(int(row["world_cup_year"]), row)
    matches_by_year = defaultdict(list)
    for m in matches:
        matches_by_year[int(m["world_cup_year"])].append(m)
    for year_matches in matches_by_year.values():
        year_matches.sort(key=lambda m: m["match_date"])

    year_links = "\n".join(f'<a href="#world-cup-{y}">{y}</a>' for y in years)
    tournaments = "\n".join(
        tournament_markup(
            y, team_rankings.get(y), matches_by_year.get(y, []),
            tournament_rankings[y], team_name,
        )
        for y in years
    )

    report_name = f"{team_info['field_prefix']}-world-cups-all.html"
    return dedent(
        f"""
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
            <meta name="description" content="Every {html.escape(team_name)} men's World Cup match and pre-tournament FIFA ranking from 1994 to 2026, in one continuous report." />
            <meta name="theme-color" content="#f2ecdf" />
            <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='44' fill='%23f2ecdf' stroke='%23b51e2e' stroke-width='8'/%3E%3Cpath d='M24 50h52M50 24v52' stroke='%23b51e2e' stroke-width='8'/%3E%3C/svg%3E" />
            <title>{html.escape(team_name)} at every World Cup · Continuous report</title>
            <style>
        {ALL_YEARS_CSS}
            </style>
          </head>
          <body>
            <a class="skip-link" href="#world-cup-1994">Skip to tournaments</a>
            <header class="report-header" id="report-top">
              <div class="report-brand"><span>XI</span><p>The World Cup Index<br /><strong>{html.escape(team_name)} / Complete Report</strong></p></div>
            </header>

            <main>
              <section class="report-intro" aria-labelledby="report-title">
                <div>
                  <h1 id="report-title">{html.escape(team_name)} at every ranked World Cup.</h1>
                </div>
                <p>{html.escape(team_name)}’s final pre-tournament FIFA rank, every opponent, every final score and the opponent’s rank—all without switching tabs.</p>
              </section>

              <nav class="year-index" aria-label="Jump to World Cup year">
                {year_links}
              </nav>

              <div class="tournaments">
                {tournaments}
              </div>

              <section class="method">
                <p class="eyebrow">Sources & method</p>
                <h2>Scores from FIFA. Ranks from the final list before kick-off.</h2>
                <p>Penalty shootout scores are kept separate from the match score. Ranks are sourced from pinned Wikipedia revisions for each tournament.</p>
              </section>
            </main>
          </body>
        </html>
        """
    ).strip() + "\n", report_name


ALL_YEARS_CSS = dedent("""
    :root {
      --paper: oklch(95% 0.018 84);
      --paper-deep: oklch(90% 0.027 76);
      --ink: oklch(20% 0.03 252);
      --ink-soft: oklch(39% 0.025 252);
      --rule: oklch(74% 0.028 76);
      --red: oklch(50% 0.205 27);
      --red-dark: oklch(38% 0.17 27);
      --blue: oklch(48% 0.13 252);
      --green: oklch(49% 0.12 151);
      --amber: oklch(65% 0.14 78);
      --font-display: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
      --font-ui: "Avenir Next", Avenir, "Gill Sans", "Trebuchet MS", sans-serif;
      --page: min(94vw, 1480px);
    }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      min-width: 20rem;
      margin: 0;
      color: var(--ink);
      background: linear-gradient(90deg, transparent 49.94%, oklch(72% 0.02 80 / .18) 50%, transparent 50.06%), var(--paper);
      font-family: var(--font-ui);
      -webkit-font-smoothing: antialiased;
    }
    body::before {
      position: fixed; inset: 0; z-index: -1; pointer-events: none; content: ""; opacity: .2;
      background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.92' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.08'/%3E%3C/svg%3E");
    }
    a { color: inherit; text-underline-offset: .25em; }
    :focus-visible { outline: 3px solid var(--blue); outline-offset: 3px; }
    .skip-link { position: fixed; top: .75rem; left: .75rem; z-index: 10; padding: .8rem 1rem; color: var(--paper); background: var(--ink); transform: translateY(-160%); }
    .skip-link:focus { transform: translateY(0); }
    .report-header, main > section, .tournaments, .report-footer { width: var(--page); margin-inline: auto; }
    .report-header { display: flex; min-height: 4.5rem; align-items: center; justify-content: space-between; padding-block: .65rem; border-bottom: 1px solid var(--ink); }
    .report-brand { display: flex; gap: .75rem; align-items: center; }
    .report-brand > span { display: grid; width: 2.5rem; height: 2.5rem; place-items: center; border: 2px solid var(--red); border-radius: 50%; color: var(--red); font-family: var(--font-display); font-size: 1rem; font-weight: 700; }
    .report-brand p, .edition { margin: 0; font-size: .72rem; font-weight: 700; letter-spacing: .12em; line-height: 1.45; text-transform: uppercase; }
    .report-brand strong { font-family: var(--font-display); font-size: 1.1rem; letter-spacing: 0; text-transform: none; }
    .edition { color: var(--ink-soft); }
    .report-intro { display: grid; grid-template-columns: 1.5fr .65fr; gap: clamp(2rem, 6vw, 6rem); align-items: end; padding-block: 2.25rem; }
    .eyebrow, dt, .fixture-meta, .fixture-number, .side small, .fixture-outcome b { font-size: .68rem; font-weight: 800; letter-spacing: .11em; line-height: 1.2; text-transform: uppercase; }
    .eyebrow { margin: 0 0 .65rem; color: var(--red); }
    h1, h2, p { text-wrap: pretty; }
    h1, h2 { margin: 0; font-family: var(--font-display); font-weight: 600; letter-spacing: -.045em; line-height: .94; }
    h1 { max-width: 13ch; font-size: clamp(3.2rem, 6vw, 5.75rem); }
    h2 { font-size: clamp(2.2rem, 4.5vw, 4.8rem); }
    .report-intro > p { margin: 0; color: var(--ink-soft); font-family: var(--font-display); font-size: 1.05rem; line-height: 1.35; }
    .year-index { position: sticky; top: 0; z-index: 5; display: grid; width: 100%; grid-template-columns: repeat(9, 1fr); border-block: 1px solid var(--ink); background: var(--paper); }
    .year-index a { min-height: 2.5rem; padding: .72rem .4rem; border-right: 1px solid var(--rule); font-size: .7rem; font-weight: 800; text-align: center; text-decoration: none; }
    .year-index a:last-child { border-right: 0; }
    .year-index a:hover { color: var(--paper); background: var(--red); }
    .tournament { padding-block: 1.5rem; border-top: 1px solid var(--ink); scroll-margin-top: 2.6rem; }
    .tournament-facts { display: grid; grid-template-columns: repeat(6, 1fr); margin: 0 0 .75rem; color: var(--paper); background: var(--ink); }
    .tournament-facts div { padding: .65rem 1rem; border-right: 1px solid oklch(52% .03 252); }
    .tournament-facts div:last-child { border-right: 0; }
    .tournament-facts dt { color: var(--paper-deep); }
    .tournament-facts dd { margin: .3rem 0 0; font-family: var(--font-display); font-size: clamp(1.1rem, 1.7vw, 1.55rem); line-height: 1; }
    .tournament-facts .tournament-year dd { color: oklch(83% .15 28); }
    .tournament-facts .tournament-rank dd { font-variant-numeric: tabular-nums; }
    .fixtures { border-top: 1px solid var(--rule); }
    .fixture { --result: var(--amber); position: relative; display: grid; grid-template-columns: 2.4rem 8rem minmax(24rem, 1fr) 10rem; min-height: 4.6rem; align-items: center; border-bottom: 1px solid var(--rule); }
    .fixture::before { position: absolute; inset: 0 auto 0 0; width: 4px; content: ""; background: var(--result); }
    .fixture.result-win { --result: var(--green); }
    .fixture.result-loss { --result: var(--red); }
    .fixture.result-scheduled { --result: var(--ink-soft); background: repeating-linear-gradient(-45deg, transparent 0 14px, var(--paper-deep) 14px 15px); }
    .fixture-number { color: var(--ink-soft); text-align: center; }
    .fixture-meta { display: flex; align-self: stretch; flex-direction: column; gap: .25rem; justify-content: center; padding-inline: .8rem; border-inline: 1px solid var(--rule); }
    .fixture-meta strong { color: var(--red-dark); }
    .fixture-meta time { color: var(--ink-soft); letter-spacing: .04em; }
    .fixture-score { display: grid; grid-template-columns: 1fr auto auto auto 1fr; gap: clamp(.55rem, 1.4vw, 1.25rem); align-items: center; padding-inline: 1rem; }
    .side span { display: block; font-family: var(--font-display); font-size: clamp(1.05rem, 1.5vw, 1.35rem); font-weight: 600; }
    .side small { display: inline-block; margin-top: .2rem; padding: .18rem .38rem; border: 1px solid var(--blue); border-radius: 999px; color: var(--blue); letter-spacing: .04em; }
    .opponent-side { text-align: right; }
    .fixture-score > strong { font-family: var(--font-display); font-size: clamp(2rem, 2.8vw, 2.6rem); font-weight: 600; font-variant-numeric: tabular-nums; line-height: .8; }
    .fixture-score > i { color: var(--ink-soft); font-style: normal; }
    .fixture-outcome { display: flex; flex-direction: column; gap: .25rem; padding-left: .8rem; }
    .fixture-outcome b { align-self: flex-start; min-width: 3.4rem; padding: .3rem .5rem; color: var(--paper); background: var(--result); text-align: center; }
    .result-scheduled .fixture-outcome b { border: 1px solid var(--ink-soft); color: var(--ink); background: var(--paper); }
    .fixture-outcome span { font-family: var(--font-display); }
    .fixture-outcome small { color: var(--ink-soft); font-size: .68rem; }
    .dnq-note { display: grid; min-height: 7rem; grid-template-columns: .5fr 1.5fr; align-items: center; border-block: 1px solid var(--rule); }
    .dnq-note strong { color: var(--red); font-family: var(--font-display); font-size: 2rem; }
    .dnq-note p { max-width: 45rem; color: var(--ink-soft); line-height: 1.55; }
    .tournament-sources { display: flex; gap: 1.25rem; justify-content: flex-end; padding-top: .65rem; font-size: .72rem; font-weight: 700; }
    .method { display: grid; grid-template-columns: .35fr 1fr 1fr; gap: 2rem; padding-block: 2.75rem; border-top: 1px solid var(--ink); }
    .method h2 { font-size: clamp(2rem, 3.3vw, 3.5rem); }
    .method > p:last-child { margin: 0; color: var(--ink-soft); line-height: 1.6; }
    .report-footer { display: flex; justify-content: space-between; padding-block: 1rem 1.5rem; border-top: 1px solid var(--ink); color: var(--ink-soft); font-size: .68rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }

    @media (max-width: 900px) {
      .report-intro { grid-template-columns: 1fr; min-height: 0; }
      .fixture { grid-template-columns: 2.8rem 9rem 1fr; }
      .fixture-outcome { grid-column: 2 / -1; display: grid; grid-template-columns: auto 1fr; padding: .8rem 1rem; border-top: 1px solid var(--rule); }
      .fixture-outcome small { grid-column: 2; }
      .source-strip, .method { grid-template-columns: 1fr 1fr; }
    }

    @media (max-width: 640px) {
      :root { --page: min(100% - 1.25rem, 1480px); }
      .edition { display: none; }
      .report-brand strong { font-size: 1.05rem; }
      .report-intro { gap: 1rem; padding-block: 2rem; }
      h1 { font-size: clamp(2.8rem, 13vw, 4rem); }
      .year-index { overflow-x: auto; grid-template-columns: repeat(9, 4.7rem); }
      .tournament { padding-block: 1.25rem; }
      .tournament-facts { grid-template-columns: repeat(3, 1fr); }
      .tournament-facts div:nth-child(3) { border-right: 0; }
      .tournament-facts div:nth-child(-n + 3) { border-bottom: 1px solid oklch(52% .03 252); }
      .fixture { grid-template-columns: 2rem 1fr; padding-block: 0; }
      .fixture-number { grid-row: 1 / 4; }
      .fixture-meta { flex-direction: row; align-self: auto; justify-content: space-between; padding: .5rem .35rem .4rem .65rem; border: 0; border-bottom: 1px solid var(--rule); }
      .fixture-score { grid-template-columns: minmax(0, 1fr) auto auto auto minmax(0, 1fr); gap: .4rem; padding: .7rem .35rem .7rem .65rem; }
      .side span { overflow: hidden; font-size: 1.05rem; text-overflow: ellipsis; }
      .side small { font-size: .54rem; }
      .fixture-score > strong { font-size: 2.2rem; }
      .fixture-outcome { grid-column: 2; padding: .5rem 0 .5rem .65rem; }
      .dnq-note { display: block; min-height: 0; padding-block: 1rem; }
      .tournament-sources { flex-direction: column; gap: .5rem; align-items: flex-start; }
      .tournament-sources a { min-height: 2rem; line-height: 2rem; }
      .method { display: block; }
      .method { padding-block: 2rem; }
      .method h2, .method > p:last-child { margin-top: 1rem; }
      .report-footer { display: block; line-height: 1.6; }
      .report-footer span { display: block; }
    }

    @media print {
      :root { --paper: white; --page: 100%; }
      body { background: white; font-size: 10pt; }
      body::before, .skip-link, .year-index, .tournament-sources a:last-child { display: none; }
      .report-header, main > section, .tournaments, .report-footer { width: 100%; }
      .report-intro { min-height: auto; padding-block: 2rem; }
      .tournament { break-before: page; padding-block: 1.5rem; }
      .tournament-facts { margin-block: 0 1rem; print-color-adjust: exact; }
      .fixture { min-height: 4.8rem; grid-template-columns: 2rem 7.5rem 1fr 9rem; break-inside: avoid; }
      .fixture-score > strong { font-size: 2rem; }
      .side span { font-size: 1rem; }
      .fixture::before, .fixture-outcome b { print-color-adjust: exact; }
      .method { break-before: page; }
    }
""").strip()


def main(args):
    output_directory = args.output_dir
    if not output_directory.is_absolute():
        output_directory = PROJECT_DIRECTORY / output_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    rankings = read_csv(RANKINGS_PATH)
    teams = discover_teams(rankings)

    generated = 0
    skipped = 0
    for fifa_code, team_info in sorted(teams.items()):
        appearances = sum(1 for row in rankings if row["fifa_code"] == fifa_code)
        if appearances == 0:
            skipped += 1
            logging.info("Skipped %s — never qualified for a recorded World Cup", team_info["name"])
            continue
        matches = load_matches(team_info)
        report, report_name = build_report(rankings, matches, team_info, fifa_code)
        output_path = output_directory / report_name
        output_path.write_text(report, encoding="utf-8")
        generated += 1
        logging.info("Wrote %s", output_path.name)

    logging.info("Generated %d team reports, skipped %d in %s", generated, skipped, output_directory)

    import subprocess

    index_script = PROJECT_DIRECTORY / "generate_index.py"
    subprocess.run([str(index_script)], check=True)

    db_script = PROJECT_DIRECTORY / "build_database.py"
    subprocess.run([str(db_script)], check=True)

    effectiveness_script = PROJECT_DIRECTORY / "generate_effectiveness_report.py"
    subprocess.run([str(effectiveness_script)], check=True)

    logging.info("Index, database, and effectiveness report generated")


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
