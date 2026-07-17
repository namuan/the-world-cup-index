"use strict";

const RANKINGS_URL = "data/world_cup_rankings.csv";
const MATCHES_URL = "data/england_world_cup_matches.csv";
const TEAM = Object.assign({ name: "England", code: "ENG" }, window.__TEAM__);

const TEAM_POSSESSIVE = TEAM.name.endsWith("s") ? `${TEAM.name}’` : `${TEAM.name}’s`;
const TOURNAMENT_SOURCES = {
  1994: "https://www.fifa.com/en/tournaments/mens/worldcup/usa1994",
  1998: "https://www.fifa.com/en/tournaments/mens/worldcup/france1998",
  2002: "https://www.fifa.com/en/tournaments/mens/worldcup/koreajapan2002",
  2006: "https://www.fifa.com/en/tournaments/mens/worldcup/germany2006",
  2010: "https://www.fifa.com/en/tournaments/mens/worldcup/southafrica2010",
  2014: "https://www.fifa.com/en/tournaments/mens/worldcup/brazil2014",
  2018: "https://www.fifa.com/en/tournaments/mens/worldcup/russia2018",
  2022: "https://www.fifa.com/en/tournaments/mens/worldcup/qatar2022",
  2026: "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026",
};

const ORDINAL_WORDS = {
  1: "first",
  2: "second",
  3: "third",
  4: "fourth",
  5: "fifth",
  6: "sixth",
  7: "seventh",
  8: "eighth",
  9: "ninth",
  10: "tenth",
  11: "eleventh",
  12: "twelfth",
};

const state = {
  rankings: [],
  matches: [],
  years: [],
  year: 2026,
};

const elements = {
  yearTabs: document.querySelector("#year-tabs"),
  heroYear: document.querySelector("#hero-year"),
  heroTitle: document.querySelector("#hero-title"),
  heroDeck: document.querySelector("#hero-deck"),
  rankStamp: document.querySelector("#rank-stamp"),
  heroRank: document.querySelector("#hero-rank"),
  rankDate: document.querySelector("#rank-date"),
  matchesPlayed: document.querySelector("#matches-played"),
  resultRecord: document.querySelector("#result-record"),
  goalRecord: document.querySelector("#goal-record"),
  tournamentReached: document.querySelector("#tournament-reached"),
  matchLedger: document.querySelector("#match-ledger"),
  noTournament: document.querySelector("#no-tournament"),
  historyChart: document.querySelector("#history-chart"),
  matchSource: document.querySelector("#match-source"),
  rankingSource: document.querySelector("#ranking-source"),
  loadError: document.querySelector("#load-error"),
};

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    const next = text[index + 1];
    if (character === '"' && quoted && next === '"') {
      field += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && next === "\n") index += 1;
      row.push(field);
      if (row.some((value) => value.length)) rows.push(row);
      row = [];
      field = "";
    } else {
      field += character;
    }
  }

  if (field.length || row.length) {
    row.push(field);
    rows.push(row);
  }

  const [headers, ...records] = rows;
  return records.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])));
}

function numberOrNull(value) {
  return value === "" || value === undefined ? null : Number(value);
}

function normaliseRanking(record) {
  return {
    ...record,
    world_cup_year: Number(record.world_cup_year),
    fifa_rank: Number(record.fifa_rank),
  };
}

function normaliseMatch(record) {
  const prefix = Object.keys(record).find(
    (key) => key.endsWith("_rank") && key !== "opponent_rank" && key !== "fifa_rank",
  );
  const baseField = prefix ? prefix.replace("_rank", "") : "england";

  return {
    ...record,
    world_cup_year: Number(record.world_cup_year),
    team_rank: Number(record[`${baseField}_rank`]),
    opponent_rank: Number(record.opponent_rank),
    team_goals: numberOrNull(record[`${baseField}_goals`]),
    opponent_goals: numberOrNull(record.opponent_goals),
    team_shootout_goals: numberOrNull(record[`${baseField}_shootout_goals`]),
    opponent_shootout_goals: numberOrNull(record.opponent_shootout_goals),
    extra_time: record.extra_time.toLocaleLowerCase() === "true",
  };
}

function formatDate(isoDate, short = false) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: short ? "short" : "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${isoDate}T00:00:00Z`));
}

function ordinalWord(rank) {
  return ORDINAL_WORDS[rank] ?? `number ${rank}`;
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function svgElement(tag, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, value));
  return node;
}

function teamRanking(year = state.year) {
  return state.rankings.find((record) => record.world_cup_year === year && record.fifa_code === TEAM.code);
}

function tournamentRanking(year = state.year) {
  return state.rankings.find((record) => record.world_cup_year === year);
}

function matchesForYear() {
  return state.matches
    .filter((match) => match.world_cup_year === state.year)
    .sort((a, b) => a.match_date.localeCompare(b.match_date));
}

function renderYearTabs() {
  elements.yearTabs.replaceChildren();
  state.years.forEach((year) => {
    const button = makeElement("button", "year-tab", year);
    button.type = "button";
    button.role = "tab";
    button.id = `year-tab-${year}`;
    button.setAttribute("aria-controls", "matches");
    button.setAttribute("aria-selected", String(year === state.year));
    button.tabIndex = year === state.year ? 0 : -1;
    button.addEventListener("click", () => selectYear(year));
    button.addEventListener("keydown", handleYearKeydown);
    elements.yearTabs.append(button);
  });
}

function handleYearKeydown(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const currentIndex = state.years.indexOf(state.year);
  let nextIndex = currentIndex;
  if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % state.years.length;
  if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + state.years.length) % state.years.length;
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = state.years.length - 1;
  selectYear(state.years[nextIndex]);
}

function selectYear(year) {
  const retainTabFocus = document.activeElement?.classList.contains("year-tab");
  state.year = year;
  window.history.replaceState(null, "", `#${year}`);
  render();
  if (retainTabFocus) document.querySelector(`#year-tab-${year}`).focus();
}

function renderHero(matches) {
  const ranking = teamRanking();
  const completed = matches.filter((match) => match.status === "completed");
  const scheduled = matches.filter((match) => match.status === "scheduled");
  elements.heroYear.textContent = state.year;

  if (!ranking) {
    elements.heroTitle.textContent = `${TEAM.name} did not reach the 1994 World Cup.`;
    elements.heroDeck.textContent = "No tournament appearance means no pre-tournament rank or match record.";
    elements.heroRank.textContent = "—";
    elements.rankDate.textContent = "Did not qualify";
    elements.rankStamp.setAttribute("aria-label", `${TEAM.name} did not qualify and has no tournament ranking`);
    return;
  }

  elements.heroTitle.replaceChildren(
    document.createTextNode(`${TEAM.name} arrived ranked `),
    makeElement("span", "", ordinalWord(ranking.fifa_rank)),
    document.createTextNode(" in the world."),
  );
  elements.heroDeck.textContent = scheduled.length
    ? `${completed.length} matches played. ${scheduled.length === 1 ? "One more to come." : `${scheduled.length} more to come.`}`
    : `${completed.length} matches played from the group stage to ${completed.at(-1).stage.toLocaleLowerCase()}.`;
  elements.heroRank.textContent = ranking.fifa_rank;
  elements.rankDate.textContent = formatDate(ranking.ranking_date, true);
  elements.rankStamp.setAttribute("aria-label", `${TEAM.name} FIFA rank ${ranking.fifa_rank}, published ${formatDate(ranking.ranking_date)}`);
}

function reachedLabel(matches) {
  if (!matches.length) return "Did not qualify";
  const scheduled = matches.find((match) => match.status === "scheduled");
  if (scheduled) return scheduled.stage;
  if (state.year === 2018) return "Fourth place";
  return matches.at(-1).stage;
}

function renderSummary(matches) {
  const completed = matches.filter((match) => match.status === "completed");
  const wins = completed.filter((match) => match.result === "win").length;
  const draws = completed.filter((match) => match.result === "draw").length;
  const losses = completed.filter((match) => match.result === "loss").length;
  const goalsFor = completed.reduce((total, match) => total + match.team_goals, 0);
  const goalsAgainst = completed.reduce((total, match) => total + match.opponent_goals, 0);

  elements.matchesPlayed.textContent = completed.length;
  elements.resultRecord.textContent = completed.length ? `${wins}W · ${draws}D · ${losses}L` : "—";
  elements.goalRecord.textContent = completed.length ? `${goalsFor} for · ${goalsAgainst} against` : "—";
  elements.tournamentReached.textContent = reachedLabel(matches);
}

function resultLabel(result) {
  return {
    win: "Win",
    draw: "Draw",
    loss: "Loss",
    scheduled: "Next",
  }[result];
}

function outcomeNote(match) {
  if (match.status === "scheduled") return `Scheduled · ${formatDate(match.match_date)}`;
  if (match.team_shootout_goals !== null) {
    const verb = match.result === "win" ? "Won" : "Lost";
    return `${verb} ${match.team_shootout_goals}–${match.opponent_shootout_goals} on penalties`;
  }
  if (match.extra_time) return "After extra time";
  return "Full time";
}

function rankComparison(match) {
  const difference = Math.abs(match.team_rank - match.opponent_rank);
  if (difference === 0) return "Both teams held the same rank";
  const subject = match.team_rank < match.opponent_rank ? TEAM.name : match.opponent;
  return `${subject} ranked ${difference} ${difference === 1 ? "place" : "places"} higher`;
}

function teamBlock(name, rank, score, opponent = false) {
  const block = makeElement("div", `score-team${opponent ? " opponent" : ""}`);
  const identity = makeElement("div", "team-identity");
  identity.append(makeElement("span", "team-name", name));
  identity.append(makeElement("span", "rank-chip", `FIFA #${rank}`));
  const scoreNumber = makeElement("strong", "score-number", score === null ? "—" : score);
  block.append(identity, scoreNumber);
  return block;
}

function renderMatches(matches) {
  elements.matchLedger.replaceChildren();
  elements.noTournament.hidden = matches.length > 0;
  elements.matchLedger.hidden = matches.length === 0;

  matches.forEach((match, index) => {
    const row = makeElement("article", `match-row result-${match.result}`);
    row.style.setProperty("--row-index", index);
    row.setAttribute(
      "aria-label",
      match.status === "scheduled"
        ? `${match.stage}: ${TEAM.name}, ranked ${match.team_rank}, will play ${match.opponent}, ranked ${match.opponent_rank}`
        : `${match.stage}: ${TEAM.name} ${match.team_goals}, ${match.opponent} ${match.opponent_goals}. ${outcomeNote(match)}`,
    );

    row.append(makeElement("span", "match-count", String(index + 1).padStart(2, "0")));
    const meta = makeElement("div", "match-meta");
    meta.append(makeElement("span", "match-stage", match.stage));
    meta.append(makeElement("time", "match-date", formatDate(match.match_date, true)));
    meta.lastElementChild.dateTime = match.match_date;
    row.append(meta);

    const scoreboard = makeElement("div", "scoreboard");
    scoreboard.append(teamBlock(TEAM.name, match.team_rank, match.team_goals));
    const divider = makeElement("span", "score-divider");
    divider.setAttribute("aria-hidden", "true");
    scoreboard.append(divider);
    scoreboard.append(teamBlock(match.opponent, match.opponent_rank, match.opponent_goals, true));
    row.append(scoreboard);

    const outcome = makeElement("div", "match-outcome");
    outcome.append(makeElement("span", "result-badge", resultLabel(match.result)));
    outcome.append(makeElement("p", "outcome-note", outcomeNote(match)));
    outcome.append(makeElement("p", "rank-comparison", rankComparison(match)));
    row.append(outcome);
    elements.matchLedger.append(row);
  });
}

function renderHistory() {
  const appearances = state.rankings
    .filter((record) => record.fifa_code === TEAM.code)
    .sort((a, b) => a.world_cup_year - b.world_cup_year);
  const byYear = new Map(appearances.map((record) => [record.world_cup_year, record]));
  const plot = { left: 70, right: 770, top: 36, bottom: 270 };
  const rankLimit = 15;
  const xForYear = (year) => plot.left + (state.years.indexOf(year) / (state.years.length - 1)) * (plot.right - plot.left);
  const yForRank = (rank) => plot.top + ((rank - 1) / (rankLimit - 1)) * (plot.bottom - plot.top);

  elements.historyChart.replaceChildren();
  const title = svgElement("title", { id: "chart-title" });
  title.textContent = `${TEAM_POSSESSIVE} pre-tournament FIFA ranking at each World Cup`;
  const description = svgElement("desc", { id: "chart-description" });
  description.textContent = `${TEAM.name} did not qualify in 1994. ${appearances.map((record) => `${record.world_cup_year}: rank ${record.fifa_rank}`).join("; ")}.`;
  elements.historyChart.append(title, description);

  [1, 5, 10, 15].forEach((rank) => {
    const y = yForRank(rank);
    elements.historyChart.append(svgElement("line", { class: "chart-grid", x1: plot.left, x2: plot.right, y1: y, y2: y }));
    const label = svgElement("text", { class: "chart-axis", x: plot.left - 14, y: y + 4, "text-anchor": "end" });
    label.textContent = rank;
    elements.historyChart.append(label);
  });

  state.years.forEach((year) => {
    const label = svgElement("text", { class: "chart-year", x: xForYear(year), y: plot.bottom + 38, "text-anchor": "middle" });
    label.textContent = year;
    elements.historyChart.append(label);
  });

  const points = appearances.map((record) => [xForYear(record.world_cup_year), yForRank(record.fifa_rank), record]);
  const pathData = points.map(([x, y], index) => `${index ? "L" : "M"} ${x} ${y}`).join(" ");
  elements.historyChart.append(svgElement("path", { class: "chart-line", d: pathData }));

  state.years.forEach((year) => {
    const record = byYear.get(year);
    if (!record) {
      const x = xForYear(year);
      elements.historyChart.append(svgElement("circle", { class: "chart-missing-mark", cx: x, cy: yForRank(rankLimit), r: 8 }));
      const missing = svgElement("text", { class: "chart-missing", x, y: yForRank(rankLimit) - 16, "text-anchor": "middle" });
      missing.textContent = "DNQ";
      elements.historyChart.append(missing);
      return;
    }

    const x = xForYear(year);
    const y = yForRank(record.fifa_rank);
    const point = svgElement("circle", {
      class: `chart-point${year === state.year ? " is-current" : ""}`,
      cx: x,
      cy: y,
      r: 8,
      tabindex: 0,
      role: "button",
      "aria-label": `${year}, ${TEAM.name} rank ${record.fifa_rank}. Open tournament.`,
    });
    point.addEventListener("click", () => selectYear(year));
    point.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectYear(year);
      }
    });
    elements.historyChart.append(point);
    const value = svgElement("text", { class: "chart-value", x, y: Math.max(18, y - 16), "text-anchor": "middle" });
    value.textContent = record.fifa_rank;
    elements.historyChart.append(value);
  });
}

function renderSources(matches) {
  const ranking = teamRanking() ?? tournamentRanking();
  elements.matchSource.href = matches[0]?.match_source_url ?? TOURNAMENT_SOURCES[state.year];
  elements.rankingSource.href = ranking.ranking_source_url;
}

function render() {
  const matches = matchesForYear();
  renderYearTabs();
  renderHero(matches);
  renderSummary(matches);
  renderMatches(matches);
  renderHistory();
  renderSources(matches);
  document.title = `${state.year} ${TEAM.name} World Cup · Rank Room`;
}

async function initialise() {
  try {
    const [rankingsResponse, matchesResponse] = await Promise.all([fetch(RANKINGS_URL), fetch(MATCHES_URL)]);
    if (!rankingsResponse.ok || !matchesResponse.ok) throw new Error("One or more data files could not be loaded");
    state.rankings = parseCsv(await rankingsResponse.text()).map(normaliseRanking);
    state.matches = parseCsv(await matchesResponse.text()).map(normaliseMatch);
    state.years = [...new Set(state.rankings.map((record) => record.world_cup_year))].sort((a, b) => a - b);
    const hashYear = Number(window.location.hash.slice(1));
    state.year = state.years.includes(hashYear) ? hashYear : state.years.at(-1);
    render();
  } catch (error) {
    console.error("Could not load dashboard data", error);
    elements.loadError.hidden = false;
  }
}

window.addEventListener("hashchange", () => {
  const year = Number(window.location.hash.slice(1));
  if (state.years.includes(year) && year !== state.year) {
    state.year = year;
    render();
  }
});

initialise();
