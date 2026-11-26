#!/usr/bin/env python3
"""Generate a chronological, contribution-driven snake using only SVG animation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


LEVELS = {name: index for index, name in enumerate((
    "NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE",
))}
PALETTES = {
    "light": ("#e5eee6", "#bfe8cf", "#7dd0a1", "#33b872", "#00A650"),
    "dark": ("#263d32", "#1d5136", "#11743f", "#068f48", "#00A650"),
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


def live_snapshot(root: Path, svgs: dict[str, str], at: str | None, reason="") -> dict:
    """Summarize published day cells once; themes never add to contribution totals."""
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args]).decode("utf-8").strip()
    readme = (root / "README.md").read_text("utf-8")
    cards = re.findall(r'<a href="(https://wly0829.cn/projects/[^/\"]+/)">.*?<img[^>]+alt="([^\"]+)"', readme)
    source_links = sorted(set(re.findall(r'https://github.com/wlyaaaaa/([^/\s)]+)', readme)))
    images = [root / p for p in git("ls-files", "assets").splitlines() if p.endswith(".webp")]
    profile_at = git("log", "-1", "--format=%cI", "--", "README.md", "assets")
    rows = sorted((e.attrib["data-date"], int(e.attrib["data-level"]))
                  for e in ET.fromstring(svgs["light"]).iter() if "data-date" in e.attrib) if svgs else []
    if svgs:
        dark = sorted((e.attrib["data-date"], int(e.attrib["data-level"]))
                      for e in ET.fromstring(svgs["dark"]).iter() if "data-date" in e.attrib)
        if rows != dark or not rows or len({d for d, _ in rows}) != len(rows):
            raise ValueError("Light/dark calendars differ or contain no unique day cells")
    streak = longest = 0
    previous = None
    for day, level in rows:
        current = date.fromisoformat(day)
        streak = (streak + 1 if previous and current - previous == timedelta(days=1) else 1) if level else 0
        longest, previous = max(longest, streak), current
    data = dict(cards=len(cards), source_links=len(source_links), image_files=len(images),
                image_bytes=sum(p.stat().st_size for p in images),
                card_list=[dict(text=title.split("：")[0], href=href, state_text="已展示") for href, title in cards],
                contribution_days=sum(level > 0 for _, level in rows) if rows else None,
                longest_streak=longest if rows else None, data_through=rows[-1][0] if rows else None,
                calendar_days=len(rows) if rows else None,
                last_active=max((d for d, level in rows if level), default=None),
                snake_bytes=sum(len(s.encode("utf-8")) for s in svgs.values()) if svgs else None)
    files = [root / p for p in git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
             if Path(p).suffix in {".md", ".py"}]
    fingerprint = hashlib.sha256(b"".join(p.relative_to(root).as_posix().encode() + p.read_bytes() for p in sorted(files))).hexdigest()
    size = dict(at=datetime.now(timezone.utc).isoformat(), fingerprint=fingerprint,
                docs_chars=sum(len(p.read_text("utf-8-sig")) for p in files if p.suffix == ".md"),
                code_lines=sum(len(p.read_text("utf-8-sig").splitlines()) for p in files if p.suffix == ".py"))
    scope = f"图上数据到 {rows[-1][0]}；覆盖 {rows[0][0]} 至 {rows[-1][0]}；亮暗两图只算一次。" if rows else reason
    return dict(v=1, at=at, scope=scope, calendar_fingerprint=hashlib.sha256("".join(svgs.values()).encode()).hexdigest() if svgs else None,
                profile_at=profile_at, profile_scope="本仓 README 与实际配图；随主页内容更新时重取。",
                metrics=data, size=size, artifacts=[dict(at=profile_at, kind="page", title="GitHub 个人主页", status="completed", public="same",
                open=dict(source="profile.readme", href="https://github.com/wlyaaaaa"))] + ([dict(at=at, kind="svg",
                title=f"贡献小蛇（图上数据到 {rows[-1][0]}）", status="completed", public="same",
                open=dict(source="profile.snake", href="https://raw.githubusercontent.com/wlyaaaaa/wlyaaaaa/output/github-contribution-grid-snake.svg"))] if rows else []))


def write_live_snapshot(path: Path, snapshot: dict) -> None:
    previous = json.loads(path.read_text("utf-8")) if path.exists() else {}
    if snapshot.get("calendar_fingerprint") and previous.get("calendar_fingerprint") == snapshot["calendar_fingerprint"]:
        snapshot["at"] = previous["at"]
        for artifact in snapshot["artifacts"]:
            if artifact["kind"] == "svg": artifact["at"] = previous["at"]
    if previous.get("size", {}).get("fingerprint") == snapshot["size"]["fingerprint"]:
        snapshot["size"]["at"] = previous["size"]["at"]
    path.parent.mkdir(parents=True, exist_ok=True)
    # One JSON object/array per line keeps the small public receipt easy to review.
    path.write_text("{\n" + ",\n".join("  " + json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False)
                    for k, v in snapshot.items()) + "\n}\n", encoding="utf-8")


def refresh_live(root: Path, output: Path, target: Path) -> bool:
    """Read the published output at one immutable commit, without credentials."""
    svgs, at, reason = {}, None, ""
    try:
        output_ref = "refs/heads/output"
        remote = subprocess.check_output(
            ["git", "ls-remote", "--refs", "https://github.com/wlyaaaaa/wlyaaaaa.git", output_ref],
            cwd=root, text=True, timeout=25, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
        )
        sha, ref = remote.split()
        if ref != output_ref or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Could not resolve the published output commit")
        base_url = f"https://raw.githubusercontent.com/wlyaaaaa/wlyaaaaa/{sha}"
        with urllib.request.urlopen(f"{base_url}/live.snapshot.json", timeout=25) as response:
            at = json.load(response)["at"]
        if not isinstance(at, str) or datetime.fromisoformat(at).utcoffset() is None:
            raise ValueError("Published snake generation time is missing")
        for theme in PALETTES:
            name = "github-contribution-grid-snake" + ("-dark" if theme == "dark" else "") + ".svg"
            with urllib.request.urlopen(f"{base_url}/{name}", timeout=25) as response:
                svgs[theme] = response.read().decode("utf-8")
        snapshot = live_snapshot(root, svgs, at)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, ET.ParseError) as error:
        svgs, reason = {}, f"最新已发布贡献图读取失败（{type(error).__name__}）；未用本地旧图替代。"
        snapshot = live_snapshot(root, svgs, None, reason)
    output.mkdir(parents=True, exist_ok=True)
    for theme, svg in svgs.items():
        name = "github-contribution-grid-snake" + ("-dark" if theme == "dark" else "") + ".svg"
        (output / name).write_text(svg, encoding="utf-8", newline="\n")
    write_live_snapshot(target, snapshot)
    return bool(svgs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER"))
    parser.add_argument("--input-json", type=Path, help="Replay a saved GraphQL response offline.")
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--live-output", type=Path, help="Write the small public live-project receipt.")
    parser.add_argument("--refresh-live", action="store_true", help="Refresh from published SVGs; never regenerate the animation.")
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[1]
        if args.refresh_live:
            return 0 if refresh_live(root, args.output_dir, args.live_output or root / "docs/live.snapshot.json") else 1
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
        if args.live_output:
            write_live_snapshot(args.live_output, live_snapshot(root, results, datetime.now(timezone.utc).isoformat()))
        print(json.dumps(metrics(calendar, plan), ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError, urllib.error.URLError) as error:
        parser.exit(1, f"Contribution snake generation failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
