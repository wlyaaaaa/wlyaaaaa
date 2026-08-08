from __future__ import annotations

import unittest

from scripts.enhance_snake import enhance_svg


SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg">
<style>
:root{--cs:#216E39}
@keyframes c0{14.20%{fill:#9BE9A8}14.30%,100%{fill:#EBEDF0}}
@keyframes c1{28.50%{fill:#40C463}28.60%,100%{fill:#EBEDF0}}
@keyframes c2{42.80%{fill:#30A14E}42.90%,100%{fill:#EBEDF0}}
@keyframes c3{57.10%{fill:#216E39}57.20%,100%{fill:#EBEDF0}}
@keyframes c4{71.40%{fill:#40C463}71.50%,100%{fill:#EBEDF0}}
@keyframes c5{85.70%{fill:#9BE9A8}85.80%,100%{fill:#EBEDF0}}
.s{fill:var(--cs);animation:none linear 7000ms infinite}
@keyframes s0{0%,98.57%{transform:translate(0px,-16px)}1.43%{transform:translate(16px,-16px)}2.86%{transform:translate(32px,-16px)}100%{transform:translate(0px,-16px)}}
</style>
<rect class="s s0" x="0" y="0" width="14" height="14"/>
<rect class="s s1" x="1" y="1" width="12" height="12"/>
<rect class="s s2" x="2" y="2" width="11" height="11"/>
<rect class="s s3" x="3" y="3" width="10" height="10"/>
</svg>"""


class EnhanceSnakeTests(unittest.TestCase):
    def test_adds_six_tail_segments_at_real_consumption_milestones(self) -> None:
        result = enhance_svg(SAMPLE_SVG, max_segments=10)

        self.assertIn("growing-snake:v2", result)
        self.assertEqual(6, result.count('class="sg sg'))
        self.assertIn('class="sg sg4"', result)
        self.assertIn('class="sg sg9"', result)
        self.assertEqual(6, result.count("@keyframes sg-grow-"))
        self.assertIn("14.20%", result)
        self.assertIn("85.70%", result)
        self.assertIn("animation-name:s0,sg-grow-4", result)
        self.assertIn("animation-delay:-6600ms,0ms", result)
        self.assertIn("98.57%,100%{opacity:0}", result)
        self.assertNotIn("}}@keyframes", result)
        self.assertIn('<rect class="s s0"', result)

    def test_is_idempotent(self) -> None:
        once = enhance_svg(SAMPLE_SVG, max_segments=10)
        twice = enhance_svg(once, max_segments=10)

        self.assertEqual(once, twice)

    def test_adds_a_replaceable_animated_transition(self) -> None:
        result = enhance_svg(
            SAMPLE_SVG,
            max_segments=4,
            transition_text="创意决定方向 & 工程让它落地",
        )

        self.assertIn('class="sg-transition"', result)
        self.assertIn('class="sg-transition-text"', result)
        self.assertIn("创意决定方向 &amp; 工程让它落地", result)
        self.assertIn("@keyframes sg-transition-flow", result)
        self.assertIn("@keyframes sg-transition-breathe", result)
        self.assertIn("prefers-reduced-motion:reduce", result)

    def test_combines_growth_and_transition_in_one_output(self) -> None:
        result = enhance_svg(
            SAMPLE_SVG,
            max_segments=10,
            transition_text="创意决定方向 · 工程让它落地",
        )

        self.assertEqual(6, result.count('class="sg sg'))
        self.assertIn('class="sg-transition"', result)

    def test_returns_unchanged_svg_when_there_is_nothing_to_eat(self) -> None:
        no_cells = SAMPLE_SVG.replace(
            "@keyframes c0{14.20%{fill:#9BE9A8}14.30%,100%{fill:#EBEDF0}}",
            "",
        )
        for index in range(1, 6):
            no_cells = no_cells.replace(
                f"@keyframes c{index}", f"@keyframes unrelated{index}"
            )

        self.assertEqual(no_cells, enhance_svg(no_cells, max_segments=10))

    def test_rejects_an_svg_without_the_snake_animation(self) -> None:
        with self.assertRaisesRegex(ValueError, "snake animation duration"):
            enhance_svg("<svg><style></style></svg>", max_segments=10)


if __name__ == "__main__":
    unittest.main()
