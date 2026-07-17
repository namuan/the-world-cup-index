#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = []
# ///
"""
Generate the Giant-killer Index report with interactive filtering.

Usage:
  ./generate_effectiveness_report.py
"""

import html
import json
import sqlite3
import logging
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from pathlib import Path
from textwrap import dedent

PROJECT_DIRECTORY = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIRECTORY / "worldcup.db"


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
    parser.add_argument("--output-dir", default="reports", type=Path)
    parser.add_argument("-v", "--verbose", action="count", default=0, dest="verbose")
    return parser.parse_args()


def query_data(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        WITH upsets AS (
            SELECT
                team_code,
                team_rank - opponent_rank AS rank_gap,
                result, stage, world_cup_year
            FROM matches
            WHERE team_rank > opponent_rank AND result != 'scheduled'
        ),
        ranked AS (
            SELECT
                team_code,
                COUNT(*) AS total_matches,
                SUM(CASE WHEN result='win'  THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN result='draw' THEN 1 ELSE 0 END) AS draws,
                SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN result='win' AND stage NOT LIKE 'Group%' THEN 1 ELSE 0 END) AS ko_wins,
                ROUND(AVG(rank_gap), 1) AS avg_gap
            FROM upsets
            GROUP BY team_code
            HAVING wins >= 1
        )
        SELECT
            r.team_code,
            COALESCE((SELECT t.team FROM rankings t WHERE t.fifa_code = r.team_code LIMIT 1), r.team_code) AS team_name,
            r.total_matches, r.wins, r.draws, r.losses,
            r.ko_wins, r.avg_gap
        FROM ranked r
        ORDER BY r.wins DESC, r.avg_gap DESC
    """).fetchall()

    details = conn.execute("""
        SELECT team_code, team_rank, opponent_rank, opponent, stage, world_cup_year, result,
               team_rank - opponent_rank AS rank_gap
        FROM matches
        WHERE team_rank > opponent_rank AND result != 'scheduled'
        ORDER BY team_code, world_cup_year
    """).fetchall()

    conn.close()

    teams = []
    detail_map = {}
    for d in details:
        code = d["team_code"]
        detail_map.setdefault(code, []).append({
            "team_rank": d["team_rank"], "opponent_rank": d["opponent_rank"],
            "opponent": d["opponent"], "stage": d["stage"],
            "year": d["world_cup_year"], "result": d["result"],
            "rank_gap": d["rank_gap"],
        })

    for r in rows:
        code = r["team_code"]
        name = r["team_name"]
        teams.append({
            "code": code, "name": name,
            "total": r["total_matches"], "wins": r["wins"],
            "draws": r["draws"], "losses": r["losses"],
            "ko_wins": r["ko_wins"], "avg_gap": float(r["avg_gap"]),
            "details": detail_map.get(code, []),
        })

    years = sorted({d["world_cup_year"] for d in details})
    return teams, years


def main(args):
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = PROJECT_DIRECTORY / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    teams, years = query_data(DB_PATH)
    logging.info("Queried %d teams, %d years", len(teams), len(years))

    teams_json = json.dumps(teams, ensure_ascii=False)

    html_content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Giant-killer Index · World Cup</title>
  <style>
    {STYLES}
  </style>
</head>
<body>
<main>
  <header class="report-hd">
    <p class="eyebrow">The World Cup Index</p>
    <h1>Giant-killer Index</h1>
    <p>Teams beating higher-ranked opponents. Use the filters to narrow down by stage, result, year, or rank gap.</p>
  </header>

  <div class="filters" id="filters">
    <label class="filter-chip"><input type="checkbox" id="fl-stage" checked onchange="applyFilters()"> Knockout only</label>
    <label class="filter-chip"><input type="checkbox" id="fl-wins" checked onchange="applyFilters()"> Wins only</label>
    <div class="filter-group">
      <label class="filter-label">Min rank gap</label>
      <input type="range" id="fl-gap" min="1" max="50" value="1" oninput="document.getElementById('gap-val').textContent=this.value;applyFilters()">
      <span id="gap-val" class="gap-display">1</span>
    </div>
    <div class="filter-group">
      <label class="filter-label">Year</label>
      <select id="fl-year" onchange="applyFilters()">
        <option value="">All years</option>
        {''.join(f'<option value="{y}">{y}</option>' for y in years)}
      </select>
    </div>
    <input type="text" id="fl-search" class="search-input" placeholder="Search team..." oninput="applyFilters()">
  </div>

  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Team</th>
        <th class="col-hideable">All</th>
        <th>Wins</th>
        <th class="col-hideable">Draws</th>
        <th class="col-hideable">Losses</th>
        <th>Avg gap</th>
        <th></th>
      </tr>
    </thead>
    <tbody id="table-body"></tbody>
  </table>
  <p class="result-count" id="result-count"></p>
</main>

<script>
const DATA = {teams_json};
const NO_DATA = DATA.filter(t => t.wins === 0 && t.total === 0);

function applyFilters() {{
  const knockoutOnly = document.getElementById('fl-stage').checked;
  const winsOnly = document.getElementById('fl-wins').checked;
  const minGap = parseInt(document.getElementById('fl-gap').value);
  const yearFilter = document.getElementById('fl-year').value;
  const search = document.getElementById('fl-search').value.toLowerCase();

  const filtered = DATA.map(team => {{
    const details = team.details.filter(d => {{
      if (knockoutOnly && d.stage.toLowerCase().includes('group')) return false;
      if (winsOnly && d.result !== 'win') return false;
      if (d.rank_gap < minGap) return false;
      if (yearFilter && d.year !== parseInt(yearFilter)) return false;
      return true;
    }});
    const visibleWins = details.filter(d => d.result === 'win').length;
    const visibleDraws = details.filter(d => d.result === 'draw').length;
    const visibleLosses = details.filter(d => d.result === 'loss').length;
    const gaps = details.map(d => d.rank_gap);
    const avgGap = gaps.length ? (gaps.reduce((a,b) => a + b, 0) / gaps.length).toFixed(1) : 0;
    return {{ ...team, details, visibleWins, visibleDraws, visibleLosses, visibleTotal: details.length, avgGap: parseFloat(avgGap) }};
  }}).filter(team => {{
    if (search && !team.name.toLowerCase().includes(search) && !team.code.toLowerCase().includes(search)) return false;
    if (team.visibleTotal === 0) return false;
    return true;
  }});

  filtered.sort((a, b) => {{
    if (b.visibleWins !== a.visibleWins) return b.visibleWins - a.visibleWins;
    return b.avgGap - a.avgGap;
  }});

  const tbody = document.getElementById('table-body');
  tbody.innerHTML = filtered.map((t, i) => {{
    const rankClass = i === 0 ? 'rank-gold' : (i === 1 ? 'rank-silver' : (i === 2 ? 'rank-bronze' : ''));
    const detailRows = t.details
      .sort((a, b) => b.rank_gap - a.rank_gap)
      .map(d => `
        <div class="upset-row ${{d.result === 'win' ? 'result-win' : d.result === 'draw' ? 'result-draw' : 'result-loss'}}">
          <span class="upset-year">${{d.year}}</span>
          <span class="upset-stage">${{d.stage}}</span>
          <span class="upset-teams">#${{d.team_rank}} ${{t.name}}</span>
          <span class="upset-vs">v</span>
          <span class="upset-teams">#${{d.opponent_rank}} ${{d.opponent}}</span>
          <span class="upset-gap">+${{d.rank_gap}} ranks</span>
          <span class="upset-result">${{d.result === 'win' ? 'Won' : d.result === 'draw' ? 'Drew' : 'Lost'}}</span>
        </div>
      `).join('');

    return `
      <tr class="${{rankClass}}">
        <td class="rank-num">${{i + 1}}</td>
        <td class="team-name">${{t.name}} <span class="team-code">${{t.code}}</span></td>
        <td class="num col-hideable">${{t.visibleTotal}}</td>
        <td class="num wins-count">${{t.visibleWins}}</td>
        <td class="num col-hideable">${{t.visibleDraws}}</td>
        <td class="num col-hideable">${{t.visibleLosses}}</td>
        <td class="num">+${{t.avgGap.toFixed(1)}}</td>
        <td class="expand-cell"><input type="checkbox" id="x${{t.code}}" class="toggle-details" onchange="toggleDetail('d${{t.code}}', this.checked)"><label for="x${{t.code}}"></label></td>
      </tr>
      <tr class="details-row" id="d${{t.code}}">
        <td colspan="8"><div class="upset-list">${{detailRows}}</div></td>
      </tr>
    `;
  }}).join('');

  document.getElementById('result-count').textContent = `${{filtered.length}} teams shown`;
}}

function toggleDetail(id, open) {{
  const row = document.getElementById(id);
  if (row) row.classList.toggle('open', open);
}}

applyFilters();
</script>
</body>
</html>"""

    output_path = output_dir / "effectiveness.html"
    output_path.write_text(html_content, encoding="utf-8")
    logging.info("Wrote %s", output_path)


STYLES = dedent("""
    :root {
      --paper: oklch(95% 0.018 84);
      --ink: oklch(20% 0.03 252);
      --ink-soft: oklch(39% 0.025 252);
      --red: oklch(50% 0.205 27);
      --green: oklch(49% 0.12 151);
      --amber: oklch(65% 0.14 78);
      --blue: oklch(48% 0.13 252);
      --rule: oklch(74% 0.028 76);
      --font-display: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
      --font-ui: "Avenir Next", Avenir, "Gill Sans", "Trebuchet MS", sans-serif;
    }
    * { box-sizing: border-box; margin: 0; }
    body { background: var(--paper); color: var(--ink); font-family: var(--font-ui); padding: 2rem; }
    main { max-width: 56rem; margin: 0 auto; }
    .report-hd { margin-bottom: 1.5rem; }
    .eyebrow { font-size: .68rem; font-weight: 800; letter-spacing: .11em; text-transform: uppercase; color: var(--red); margin-bottom: .5rem; }
    h1 { font-family: var(--font-display); font-size: clamp(2.5rem, 5vw, 4rem); letter-spacing: -.04em; line-height: .94; margin-bottom: .5rem; }
    .report-hd p { color: var(--ink-soft); line-height: 1.5; max-width: 42rem; font-size: .9rem; }

    .filters { display: flex; flex-wrap: wrap; gap: .5rem 1rem; align-items: center; padding: .75rem 1rem; background: oklch(92% 0.01 84); border-radius: 8px; margin-bottom: 1.25rem; }
    .filter-chip { display: flex; align-items: center; gap: .35rem; font-size: .78rem; font-weight: 600; cursor: pointer; user-select: none; padding: .3rem .6rem; border: 1px solid var(--rule); border-radius: 6px; background: var(--paper); }
    .filter-chip:hover { border-color: var(--ink-soft); }
    .filter-chip input[type="checkbox"] { accent-color: var(--red); }
    .filter-group { display: flex; align-items: center; gap: .4rem; font-size: .75rem; }
    .filter-label { color: var(--ink-soft); font-weight: 600; font-size: .7rem; text-transform: uppercase; letter-spacing: .04em; }
    .filter-group input[type="range"] { width: 5rem; accent-color: var(--blue); }
    .gap-display { font-weight: 700; font-variant-numeric: tabular-nums; min-width: 1.5rem; text-align: center; }
    .filter-group select { font-family: var(--font-ui); font-size: .78rem; padding: .25rem .5rem; border: 1px solid var(--rule); border-radius: 4px; background: var(--paper); }
    .search-input { flex: 1; min-width: 8rem; font-family: var(--font-ui); font-size: .78rem; padding: .35rem .6rem; border: 1px solid var(--rule); border-radius: 6px; background: var(--paper); }
    .search-input:focus { outline: none; border-color: var(--blue); box-shadow: 0 0 0 2px oklch(48% 0.13 252 / .15); }

    table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
    thead { border-bottom: 2px solid var(--ink); }
    th { text-align: left; padding: .6rem .5rem; font-size: .65rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; color: var(--ink-soft); }
    td { padding: .65rem .5rem; border-bottom: 1px solid var(--rule); font-size: .9rem; }
    .rank-num { font-weight: 700; color: var(--ink-soft); width: 2rem; }
    .team-name { font-weight: 600; }
    .team-code { font-size: .68rem; color: var(--ink-soft); margin-left: .35rem; font-weight: 400; }
    .num { text-align: right; white-space: nowrap; }
    .wins-count { font-weight: 700; color: var(--green); }
    .rank-gold .team-name { color: oklch(55% 0.14 75); }
    .rank-silver .team-name { color: oklch(45% 0.03 240); }
    .rank-bronze .team-name { color: oklch(45% 0.08 55); }
    .rank-gold td { background: oklch(95% 0.04 75 / .25); }
    .rank-silver td { background: oklch(95% 0.01 240 / .2); }
    .rank-bronze td { background: oklch(95% 0.03 55 / .2); }

    .expand-cell { width: 2rem; text-align: center; }
    .toggle-details { display: none; }
    .toggle-details + label { cursor: pointer; display: inline-block; width: 20px; height: 20px; border: 1.5px solid var(--rule); border-radius: 3px; position: relative; }
    .toggle-details + label::after { content: '+'; position: absolute; inset: 0; display: grid; place-items: center; font-size: .85rem; font-weight: 700; color: var(--ink-soft); }
    .toggle-details:checked + label::after { content: '−'; }
    .details-row { display: none; }
    .details-row.open { display: table-row; }
    .details-row td { padding: 0 .5rem .5rem; border-bottom: 2px solid var(--rule); background: var(--paper); }
    .upset-list { display: grid; gap: 3px; padding: .5rem; }
    .upset-row { display: flex; gap: .75rem; align-items: center; padding: .35rem .5rem; border-radius: 4px; font-size: .8rem; }
    .upset-row.result-win { background: oklch(90% 0.06 151 / .3); }
    .upset-row.result-draw { background: oklch(92% 0.03 84 / .3); }
    .upset-row.result-loss { background: oklch(90% 0.03 27 / .15); }
    .upset-year { width: 3rem; font-weight: 700; font-size: .75rem; color: var(--red); font-variant-numeric: tabular-nums; }
    .upset-stage { width: 7rem; font-weight: 600; font-size: .7rem; text-transform: uppercase; color: var(--ink-soft); letter-spacing: .04em; }
    .upset-teams { font-weight: 600; }
    .upset-vs { color: var(--ink-soft); font-size: .7rem; }
    .upset-gap { margin-left: auto; font-size: .72rem; color: var(--ink-soft); white-space: nowrap; }
    .upset-result { font-weight: 800; font-size: .68rem; text-transform: uppercase; letter-spacing: .06em; min-width: 2.5rem; text-align: right; }
    .upset-row.result-win .upset-result { color: var(--green); }
    .upset-row.result-draw .upset-result { color: var(--amber); }
    .upset-row.result-loss .upset-result { color: var(--red); }
    .result-count { margin-top: .75rem; font-size: .75rem; color: var(--ink-soft); text-align: right; }

    @media (max-width: 700px) {
      body { padding: 1rem; }
      .col-hideable { display: none; }
      .upset-stage { width: 5rem; }
      .filters { padding: .5rem; }
    }
""").strip()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.verbose)
    main(args)
