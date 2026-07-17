#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = []
# ///
"""
Generate an index page listing every team report in the reports/ directory.

Usage:
  ./generate_index.py
"""

from pathlib import Path
from textwrap import dedent

PROJECT_DIRECTORY = Path(__file__).resolve().parent
REPORTS_DIR = PROJECT_DIRECTORY / "docs"


def discover_reports():
    continuous = []
    interactive = []
    for path in sorted(REPORTS_DIR.glob("*-world-cups-all.html")):
        name = path.stem.replace("-world-cups-all", "").replace("_", " ").title()
        continuous.append((name, path.name))
    for path in sorted(REPORTS_DIR.glob("*-world-cup-tabs.html")):
        name = path.stem.replace("-world-cup-tabs", "").replace("_", " ").title()
        interactive.append((name, path.name))
    return continuous, interactive


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    continuous, interactive = discover_reports()

    continuous_rows = "\n".join(
        f'            <li><a href="{href}">{name}</a></li>'
        for name, href in continuous
    )
    interactive_rows = "\n".join(
        f'            <li><a href="{href}">{name}</a></li>'
        for name, href in interactive
    )

    html = dedent(
        f"""\
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>World Cup Reports · Index</title>
          <style>
            :root {{
              --paper: oklch(95% 0.018 84);
              --ink: oklch(20% 0.03 252);
              --ink-soft: oklch(39% 0.025 252);
              --red: oklch(50% 0.205 27);
              --rule: oklch(74% 0.028 76);
              --font-display: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
              --font-ui: "Avenir Next", Avenir, "Gill Sans", "Trebuchet MS", sans-serif;
            }}
            * {{ box-sizing: border-box; }}
            body {{
              margin: 0; padding: 2rem;
              color: var(--ink); background: var(--paper);
              font-family: var(--font-ui);
            }}
            main {{ max-width: 60rem; margin: 0 auto; }}
            h1 {{ font-family: var(--font-display); font-size: clamp(2rem, 4vw, 3.5rem); margin: 0 0 .25rem; }}
            h2 {{ font-family: var(--font-display); font-size: 1.4rem; margin: 2rem 0 .75rem; padding-top: 1rem; border-top: 1px solid var(--rule); }}
            .eyebrow {{ font-size: .68rem; font-weight: 800; letter-spacing: .11em; text-transform: uppercase; color: var(--red); margin: 0 0 .5rem; }}
            p {{ color: var(--ink-soft); margin: 0 0 1.5rem; }}
            ul {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr)); gap: .35rem; list-style: none; padding: 0; margin: 0; }}
            li {{ }}
            a {{
              display: block; padding: .5rem .75rem;
              color: var(--ink); text-decoration: none;
              border: 1px solid var(--rule); border-radius: 4px;
              font-size: .88rem;
            }}
            a:hover {{ border-color: var(--red); color: var(--red); }}
            .counts {{ font-size: .8rem; color: var(--ink-soft); }}
          </style>
        </head>
        <body>
        <main>
          <p class="eyebrow">The World Cup Index</p>
          <h1>Team reports</h1>
          <p>Every team's pre-tournament FIFA ranking at each World Cup from 1994 to 2026, in one continuous page. <span class="counts">{len(continuous)} continuous reports</span></p>
          <ul>
        {continuous_rows}
          </ul>
          <h2>Interactive dashboards</h2>
          <p>Teams with full match data. Switch between tournaments, explore every fixture and ranking history. <span class="counts">{len(interactive)} dashboards</span></p>
          <ul>
        {interactive_rows}
          </ul>
        </main>
        </body>
        </html>
        """
    )

    index_path = REPORTS_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"Wrote {index_path} ({len(continuous)} continuous, {len(interactive)} interactive)")


if __name__ == "__main__":
    main()
