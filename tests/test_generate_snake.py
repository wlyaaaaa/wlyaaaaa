from datetime import date, timedelta
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from scripts.generate_snake import (
    Calendar, Day, HOLD_MS, INITIAL_LENGTH, LEVELS, MAX_LENGTH, PALETTES,
    RETURN_MS, SNAKE_COLORS, fetch_calendar, parse_calendar, plan_snake, render_svg,
)

NS = {"s": "http://www.w3.org/2000/svg"}


def calendar(rows: list[list[int]]) -> Calendar:
    origin = date(2025, 9, 28)
    return Calendar(tuple(
        Day((origin + timedelta(days=7 * x + y)).isoformat(), x, y, level * 7, level)
        for x, week in enumerate(rows) for y, level in enumerate(week)
    ), len(rows))


def response(value: Calendar) -> dict:
    names = list(LEVELS)
    return {"data": {"user": {"contributionsCollection": {"contributionCalendar": {
        "weeks": [{"contributionDays": [
            {"date": d.date, "weekday": d.row, "contributionCount": d.count,
             "contributionLevel": names[d.level]}
            for d in value.days if d.column == column
        ]} for column in range(value.columns)]
    }}}}}


class DataTests(unittest.TestCase):
    def test_maps_api_levels_without_rebinning_counts(self) -> None:
        source = calendar([[0, 1, 2, 3, 4]])
        payload = response(source)
        day = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"][0]["contributionDays"][1]
        day["contributionCount"] = 100000
        actual = parse_calendar(payload)
        self.assertEqual([0, 1, 2, 3, 4], [d.level for d in actual.days])

    def test_fetch_refines_the_exact_profile_date_window(self) -> None:
        source = calendar([[0] * 7, [4]])
        first, final = response(calendar([[0] * 7, [1]])), response(source)
        with patch("scripts.generate_snake._query_calendar", side_effect=[first, final]) as query:
            self.assertEqual(4, parse_calendar(fetch_calendar("example", "test-token")).today.level)
        self.assertEqual(2, query.call_count)
        self.assertEqual(("example", "test-token", "2025-09-28T00:00:00Z", "2025-10-05T23:59:59Z"), query.call_args.args)

    def test_rejects_graphql_errors_and_unknown_levels(self) -> None:
        with self.assertRaises(ValueError):
            parse_calendar({"errors": [{"message": "Unavailable"}]})
        payload = response(calendar([[0]]))
        payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"][0]["contributionDays"][0]["contributionLevel"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "Unknown"):
            parse_calendar(payload)

    def test_rejects_a_changed_second_response_window(self) -> None:
        with patch("scripts.generate_snake._query_calendar", side_effect=[
            response(calendar([[0] * 7, [1]])), response(calendar([[0] * 7, [1, 1]])),
        ]):
            with self.assertRaisesRegex(ValueError, "changed the calendar range"):
                fetch_calendar("example", "test-token")


class RouteTests(unittest.TestCase):
    def test_empty_columns_only_take_one_horizontal_step(self) -> None:
        source = calendar([[0] * 7, [0, 1, 0, 0, 2, 0, 0], [0] * 7, [0] * 7, [1]])
        plan = plan_snake(source)
        for column in [0, 2, 3]:
            self.assertEqual(1, sum(x == column for x, _ in plan.route))
        for column in [2, 3]:
            index = next(i for i, (x, _) in enumerate(plan.route) if x == column)
            self.assertEqual((1, 0), tuple(a - b for a, b in zip(plan.route[index], plan.route[index - 1])))

    def test_active_columns_cover_all_contributions(self) -> None:
        source = calendar([[1, 0, 2, 0, 4, 0, 1], [0, 1, 0, 3, 0, 1, 0], [2, 0, 1]])
        plan = plan_snake(source)
        self.assertEqual({d.date for d in source.days if d.level}, set(plan.eaten))
        for d in source.days:
            if d.level:
                self.assertEqual((d.column, d.row), plan.route[plan.eaten[d.date]])

    def test_nearer_end_then_farther_end_and_tie_are_deterministic(self) -> None:
        source = calendar([[0, 0, 0, 1, 0, 0, 0], [0, 1, 0, 0, 0, 1, 0], [1] * 7, [1]])
        plan = plan_snake(source)
        rows = [y for x, y in plan.route if x == 1]
        self.assertEqual([3, 2, 1, 2, 3, 4, 5], rows)

    def test_final_partial_week_ends_at_today_without_future_rows(self) -> None:
        for today_level in [0, 4]:
            source = calendar([[1] * 7, [1] * 7, [0] * 7, [today_level]])
            plan = plan_snake(source)
            self.assertEqual((3, 0), plan.route[-1])
            self.assertEqual([(3, 0)], [p for p in plan.route if p[0] == 3])
            self.assertEqual(1, sum(x == 2 for x, _ in plan.route))

    def test_no_column_backtracking_no_jumps_and_body_stays_in_bounds(self) -> None:
        source = calendar([[1, 0, 0, 2, 0, 0, 3], [0] * 7, [4, 0, 0, 1]])
        plan = plan_snake(source)
        for left, right in zip(plan.route, plan.route[1:]):
            self.assertGreaterEqual(right[0], left[0])
            self.assertEqual(1, abs(right[0] - left[0]) + abs(right[1] - left[1]))
        self.assertTrue(all(0 <= x < source.columns and 0 <= y < 7 for x, y in plan.history))
        self.assertEqual(3, len(set(plan.history[:3])))

    def test_score_grows_on_first_eat_only_and_is_capped(self) -> None:
        source = calendar([[1, 4, 2, 3, 4, 1, 4]] * 8 + [[4]])
        plan = plan_snake(source)
        self.assertEqual(sum(d.level for d in source.days), plan.score)
        seen, score = set(), 0
        lookup = {(d.column, d.row): d for d in source.days}
        for step, point in enumerate(plan.route):
            day = lookup.get(point)
            if day and day.level and day.date not in seen:
                seen.add(day.date)
                score += day.level
            self.assertEqual(min(MAX_LENGTH, INITIAL_LENGTH + score // plan.points_per_segment), plan.lengths[step])
        self.assertGreaterEqual(plan.lengths[-1], 15)
        self.assertLessEqual(max(plan.lengths), MAX_LENGTH)

    def test_empty_calendar_moves_horizontally_to_today(self) -> None:
        source = calendar([[0] * 7] * 5 + [[0, 0, 0]])
        plan = plan_snake(source)
        self.assertEqual(tuple((x, 2) for x in range(6)), plan.route)
        self.assertEqual((3,) * 6, plan.lengths)

    def test_dense_year_speeds_up_to_stay_below_30_seconds(self) -> None:
        plan = plan_snake(calendar([[4] * 7] * 52 + [[4]]))
        self.assertLess(plan.step_ms, 90)
        self.assertLessEqual(plan.cycle_ms, 25000)
        self.assertEqual(HOLD_MS + RETURN_MS, plan.cycle_ms - plan.move_ms)


class SvgTests(unittest.TestCase):
    def test_palette_dates_and_xml_are_preserved(self) -> None:
        source = calendar([[0, 1, 2, 3, 4]])
        plan = plan_snake(source)
        for theme in ["light", "dark"]:
            svg = ET.fromstring(render_svg(source, plan, theme))
            cells = svg.findall("s:rect[@data-date]", NS)
            self.assertEqual([d.date for d in source.days], [c.get("data-date") for c in cells])
            self.assertEqual(list(PALETTES[theme]), [c.get("fill") for c in cells])
            self.assertTrue(all(c.get("rx") == "3" for c in cells))
            self.assertTrue(all(s.get("fill") == SNAKE_COLORS[theme] for s in svg.findall("s:g[@data-segment]", NS)))

    def test_eat_and_growth_times_match_head_arrival_with_shared_cycle(self) -> None:
        source = calendar([[0, 1, 4, 3, 2, 1, 4], [1] * 7, [4]])
        plan = plan_snake(source)
        svg = ET.fromstring(render_svg(source, plan, "light"))
        for cell in svg.findall("s:rect[@data-date]", NS):
            day = cell.get("data-date")
            animation = cell.find("s:animate", NS)
            if day in plan.eaten:
                self.assertEqual("linear", animation.get("calcMode"))
                times = [float(t) for t in animation.get("keyTimes").split(";")]
                expected = plan.eaten[day] * plan.step_ms / plan.cycle_ms
                self.assertAlmostEqual(expected, times[1] if expected else 0, places=8)
            else:
                self.assertIsNone(animation)
        for animation in svg.findall(".//s:animate", NS) + svg.findall(".//s:animateMotion", NS):
            self.assertEqual(f"{plan.cycle_ms}ms", animation.get("dur"))
            self.assertEqual("indefinite", animation.get("repeatCount"))
        for segment in svg.findall("s:g[@data-segment]", NS):
            index = int(segment.get("data-segment"))
            motion = segment.find("s:animateMotion", NS)
            times = [float(t) for t in motion.get("keyTimes").split(";")]
            self.assertAlmostEqual(plan.move_ms / plan.cycle_ms, times[-3], places=8)
            self.assertAlmostEqual((plan.move_ms + HOLD_MS) / plan.cycle_ms, times[-2], places=8)
            if index >= INITIAL_LENGTH:
                born = next(i for i, length in enumerate(plan.lengths) if length > index)
                opacity = segment.find("s:animate", NS)
                if born:
                    self.assertAlmostEqual(born * plan.step_ms / plan.cycle_ms, float(opacity.get("keyTimes").split(";")[1]), places=8)

    def test_dense_year_stays_below_150_kb_without_scripts_or_external_assets(self) -> None:
        source = calendar([[4] * 7] * 52 + [[4]])
        for theme in ["light", "dark"]:
            content = render_svg(source, plan_snake(source), theme)
            self.assertLess(len(content.encode()), 150000)
            root = ET.fromstring(content)
            self.assertFalse(root.findall('.//s:script', NS))
            self.assertFalse(root.findall('.//s:image', NS))

    def test_zero_move_calendar_head_stays_on_today(self) -> None:
        source = calendar([[0]])
        plan = plan_snake(source)
        root = ET.fromstring(render_svg(source, plan, "light"))
        head = next(g for g in root.findall('s:g[@data-segment]', NS) if g.get('data-segment') == '0')
        self.assertEqual('1;1', head.find('s:animateMotion', NS).get('keyPoints'))

    def test_head_is_larger_than_body_but_fits_an_edge_cell(self) -> None:
        source = calendar([[1] * 7, [4]])
        root = ET.fromstring(render_svg(source, plan_snake(source), "light"))
        parts = {int(g.get('data-segment')): g.find('s:rect', NS)
                 for g in root.findall('s:g[@data-segment]', NS)}
        head, body = parts[0], parts[1]
        self.assertGreater(float(head.get('width')), float(body.get('width')))
        self.assertLessEqual(float(head.get('width')), 12)
        self.assertLessEqual(float(head.get('height')), 12)


if __name__ == "__main__":
    unittest.main()
