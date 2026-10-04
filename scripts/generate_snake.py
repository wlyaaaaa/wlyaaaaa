#!/usr/bin/env python3
"""Generate a chronological, contribution-driven snake using only SVG animation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
import math
import os
from pathlib import Path
import urllib.error
import urllib.request


LEVELS = {name: index for index, name in enumerate((
    "NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE",
))}
PALETTES = {
    "light": ("#e5eee6", "#bfd6c2", "#8db495", "#4b895e", "#28643d"),
    "dark": ("#263d32", "#30523d", "#42734e", "#67a778", "#9bcca4"),
}
SNAKE_COLORS = {"light": "#b77942", "dark": "#d9ad73"}
INITIAL_LENGTH = 3
MAX_LENGTH = 16
STEP_MS = 90
HOLD_MS = 2000
RETURN_MS = 2400
PITCH = 16
QUERY = """query($login:String!,$from:DateTime,$to:DateTime){
  user(login:$login){contributionsCollection(from:$from,to:$to){
    contributionCalendar{weeks{firstDay contributionDays{
      date weekday contributionCount contributionLevel
    }}}
  }}
}"""


@dataclass(frozen=True)
class Day:
    date: str
    column: int
    row: int
    count: int
    level: int


@dataclass(frozen=True)
class Calendar:
    days: tuple[Day, ...]
    columns: int

    @property
    def today(self) -> Day:
        return self.days[-1]


@dataclass(frozen=True)
class Plan:
    route: tuple[tuple[int, int], ...]
    history: tuple[tuple[int, int], ...]
    eaten: dict[str, int]
    lengths: tuple[int, ...]
    points_per_segment: int
    score: int
    step_ms: int

    @property
    def move_ms(self) -> int:
        return (len(self.route) - 1) * self.step_ms

    @property
    def cycle_ms(self) -> int:
        return self.move_ms + HOLD_MS + self.return_ms

    @property
    def return_ms(self) -> int:
        return RETURN_MS if self.move_ms else 0


def parse_calendar(payload: dict) -> Calendar:
    if payload.get("errors"):
        raise ValueError("GitHub GraphQL returned errors; no SVG was generated")
    try:
        weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    except (KeyError, TypeError) as error:
        raise ValueError("Missing GitHub contribution calendar") from error
    days = []
    for column, week in enumerate(weeks):
        for item in week["contributionDays"]:
            parsed = date.fromisoformat(item["date"])
            row = int(item["weekday"])
            if row != (parsed.weekday() + 1) % 7:
                raise ValueError(f"Invalid weekday for {parsed}")
            if item["contributionLevel"] not in LEVELS:
                raise ValueError("Unknown GitHub contributionLevel")
            if days and item["date"] <= days[-1].date:
                raise ValueError("Contribution days must be unique and chronological")
            days.append(Day(item["date"], column, row, int(item["contributionCount"]),
                            LEVELS[item["contributionLevel"]]))
    if not days:
        raise ValueError("Empty contribution calendar")
    return Calendar(tuple(days), len(weeks))


def _query_calendar(login: str, token: str, start: str | None = None,
                    end: str | None = None) -> dict:
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {
            "login": login, "from": start, "to": end,
        }}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "github-profile-timeline-snake"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.load(response)
    parse_calendar(payload)
    return payload


def fetch_calendar(login: str, token: str) -> dict:
    """Use the exact displayed date range, not the default collection window.

    GitHub can return different contributionLevel values for its wider default
    collection window even when the calendar displays the same 365 days.
    Explicit dates preserve the profile's levels without re-binning counts.
    """
    discovery = parse_calendar(_query_calendar(login, token))
    start, end = discovery.days[0].date, discovery.today.date
    payload = _query_calendar(login, token, f"{start}T00:00:00Z", f"{end}T23:59:59Z")
    result = parse_calendar(payload)
    if (result.days[0].date, result.today.date) != (start, end):
        raise ValueError("GitHub changed the calendar range during generation; retry")
    return payload


def plan_snake(calendar: Calendar) -> Plan:
    active = {column: sorted(d.row for d in calendar.days if d.column == column and d.level)
              for column in range(calendar.columns)}
    last = calendar.columns - 1
    last_entry = min(active[last]) if active[last] else calendar.today.row
    earlier_active = [column for column in range(last) if active[column]]
    align_column = earlier_active[-1] if earlier_active else None
    row = calendar.days[0].row if earlier_active else last_entry
    route = [(0, row)]

    def sweep_to(target: int) -> None:
        nonlocal row
        while row != target:
            row += 1 if target > row else -1
            route.append((column, row))

    for column in range(calendar.columns):
        if column:
            route.append((column, row))
        if active[column]:
            low, high = active[column][0], active[column][-1]
            near, far = (low, high) if abs(row - low) <= abs(row - high) else (high, low)
            sweep_to(near)
            sweep_to(far)
        # Align before trailing empty weeks / the short final week, keeping
        # every empty column horizontal-only and avoiding future rows at entry.
        if column == align_column:
            sweep_to(last_entry)
        if column == last:
            sweep_to(calendar.today.row)

    start_row = route[0][1]
    direction = 1 if start_row <= 4 else -1
    history = [(0, start_row + 2 * direction), (0, start_row + direction), *route]
    by_position = {(d.column, d.row): d for d in calendar.days}
    total_score = sum(d.level for d in calendar.days)
    points = max(1, math.ceil(total_score / (MAX_LENGTH - INITIAL_LENGTH)))
    eaten: dict[str, int] = {}
    score = 0
    lengths = []
    for step, position in enumerate(route):
        day = by_position.get(position)
        if day and day.level and day.date not in eaten:
            eaten[day.date] = step
            score += day.level
        lengths.append(min(MAX_LENGTH, INITIAL_LENGTH + score // points))
    if len(eaten) != sum(bool(d.level) for d in calendar.days):
        raise ValueError("Route missed a contribution day")
    steps = len(route) - 1
    step_ms = STEP_MS
    if steps * STEP_MS + HOLD_MS + RETURN_MS > 30000:
        step_ms = max(1, (23000 - RETURN_MS) // steps)
    return Plan(tuple(route), tuple(history), eaten, tuple(lengths), points, score, step_ms)


def _fraction(value: float) -> str:
    return f"{value:.9f}".rstrip("0").rstrip(".") or "0"


def _return_route(plan: Plan) -> tuple[tuple[int, int], ...]:
    """Return below the calendar, then replay the initial three body positions."""
    if not plan.return_ms:
        return ()
    column, row = plan.route[-1]
    route = []
    for target_column, target_row in ((column, 7), (0, 7), *plan.history[:3]):
        while column != target_column or row != target_row:
            if column != target_column:
                column += 1 if target_column > column else -1
            else:
                row += 1 if target_row > row else -1
            route.append((column, row))
    return tuple(route)


def render_svg(calendar: Calendar, plan: Plan, theme: str) -> str:
    palette, snake = PALETTES[theme], SNAKE_COLORS[theme]
    width, height = calendar.columns * PITCH + 16, 152
    duration = f"{plan.cycle_ms}ms"
    background = "#f6faf5" if theme == "light" else "#14221e"
    border = "#d6e5d8" if theme == "light" else "#345141"
    point = lambda cell: (16 + cell[0] * PITCH, 32 + cell[1] * PITCH)
    coordinates = [point(cell) for cell in (*plan.history, *_return_route(plan))]
    return_start = (plan.move_ms + HOLD_MS) / plan.cycle_ms
    restore_end = (plan.move_ms + HOLD_MS + plan.return_ms * 0.65) / plan.cycle_ms
    path = "M" + "L".join(f"{x},{y}" for x, y in coordinates)
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">按周向前的 GitHub 贡献记录（{calendar.days[0].date} 至 {calendar.today.date}）</title>',
        f'<desc id="desc">{calendar.days[0].date} 至 {calendar.today.date}，从左到右逐周吃格，停在今天两秒后沿底部回到起点，无限循环。</desc>',
        f'<defs><path id="route" d="{path}"/></defs>',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="16" fill="{background}" stroke="{border}" stroke-width="1"/>',
    ]
    for index, day in enumerate(calendar.days):
        x, y = point((day.column, day.row))
        output.append(f'<rect id="d{index}" class="c" data-date="{day.date}" data-level="{day.level}" x="{x - 6}" y="{y - 6}" width="12" height="12" rx="3" fill="{palette[day.level]}">')
        if day.date in plan.eaten:
            arrival = plan.eaten[day.date] * plan.step_ms
            if arrival:
                values = f"{palette[day.level]};{palette[day.level]};{palette[0]};{palette[0]};{palette[day.level]};{palette[day.level]}"
                at = _fraction(arrival / plan.cycle_ms)
                times = f"0;{at};{at};{_fraction(return_start)};{_fraction(restore_end)};1"
            else:
                values, times = f"{palette[0]};{palette[0]}", "0;1"
            output.append(f'<animate attributeName="fill" values="{values}" keyTimes="{times}" calcMode="linear" dur="{duration}" repeatCount="indefinite"/>')
        output.append('</rect>')
    today_x, today_y = point((calendar.today.column, calendar.today.row))
    output.append(f'<rect x="{today_x - 7.5}" y="{today_y - 7.5}" width="15" height="15" rx="4" fill="none" stroke="{snake}" stroke-width="1"/>')
    total_edges = len(coordinates) - 1
    food_edges = len(plan.history) - 1
    movement_end = plan.move_ms / plan.cycle_ms
    for segment in reversed(range(max(plan.lengths))):
        start = max(0, 2 - segment) / total_edges
        finish = max(0, food_edges - segment) / total_edges
        loop_finish = max(0, total_edges - segment) / total_edges
        delay_ms = max(0, segment - 2) * plan.step_ms
        if not plan.move_ms:
            points, times = f"{_fraction(start)};{_fraction(start)}", "0;1"
        elif delay_ms >= plan.move_ms:
            points, times = "0;0", "0;1"
        elif delay_ms:
            points = f"0;0;{_fraction(finish)};{_fraction(finish)}"
            times = f"0;{_fraction(delay_ms / plan.cycle_ms)};{_fraction(movement_end)};1"
        else:
            points = f"{_fraction(start)};{_fraction(finish)};{_fraction(finish)}"
            times = f"0;{_fraction(movement_end)};1"
        if plan.return_ms:
            points = points.rsplit(";", 1)[0] + f";{_fraction(finish)};{_fraction(loop_finish)}"
            times = times.rsplit(";", 1)[0] + f";{_fraction(return_start)};1"
        output.append(f'<g class="s" data-segment="{segment}" fill="{snake}" opacity="{1 if segment < INITIAL_LENGTH else 0}">')
        size = 12 if segment == 0 else 10
        output.append(f'<rect x="{-size / 2:g}" y="{-size / 2:g}" width="{size}" height="{size}" rx="4"/>')
        output.append(f'<animateMotion dur="{duration}" repeatCount="indefinite" calcMode="linear" keyPoints="{points}" keyTimes="{times}"><mpath xlink:href="#route"/></animateMotion>')
        if segment >= INITIAL_LENGTH:
            born = next(step for step, length in enumerate(plan.lengths) if length > segment)
            if plan.return_ms:
                # A first-cell score starts growing on the first move, so every
                # moving cycle begins and ends with the same three segments.
                at = _fraction(max(1, born) * plan.step_ms / plan.cycle_ms)
                output.append(f'<animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;{at};{at};{_fraction(return_start)};{_fraction(restore_end)};1" calcMode="linear" dur="{duration}" repeatCount="indefinite"/>')
            else:
                output.append(f'<animate attributeName="opacity" values="1;1" dur="{duration}" repeatCount="indefinite"/>')
        output.append('</g>')
    output.append('</svg>')
    svg = "".join(output)
    if len(svg.encode()) > 150000:
        raise ValueError("Generated SVG exceeds 150 KB")
    return svg


def metrics(calendar: Calendar, plan: Plan) -> dict:
    return {"first_date": calendar.days[0].date, "today": calendar.today.date,
            "days": len(calendar.days), "weeks": calendar.columns,
            "contribution_days": len(plan.eaten), "score": plan.score,
            "points_per_segment": plan.points_per_segment,
            "initial_length": INITIAL_LENGTH, "final_length": plan.lengths[-1],
            "max_length": MAX_LENGTH, "moves": len(plan.route) - 1,
            "step_ms": plan.step_ms, "move_ms": plan.move_ms,
            "hold_ms": HOLD_MS, "return_ms": plan.return_ms, "cycle_ms": plan.cycle_ms}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER"))
    parser.add_argument("--input-json", type=Path, help="Replay a saved GraphQL response offline.")
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    try:
        if args.input_json:
            payload = json.loads(args.input_json.read_text(encoding="utf-8"))
        else:
            token = os.environ.get("GITHUB_TOKEN")
            if not args.user or not token:
                raise ValueError("--user and GITHUB_TOKEN are required for GitHub GraphQL")
            payload = fetch_calendar(args.user, token)
        calendar = parse_calendar(payload)
        plan = plan_snake(calendar)
        results = {theme: render_svg(calendar, plan, theme) for theme in PALETTES}
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for theme, svg in results.items():
            suffix = "-dark" if theme == "dark" else ""
            (args.output_dir / f"github-contribution-grid-snake{suffix}.svg").write_text(svg, encoding="utf-8", newline="\n")
        print(json.dumps(metrics(calendar, plan), ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError, urllib.error.URLError) as error:
        parser.exit(1, f"Contribution snake generation failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
