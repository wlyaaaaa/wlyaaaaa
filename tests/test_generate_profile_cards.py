from collections import Counter
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_profile_cards import GREEN, THEMES, languages_card, stats_card


SVG = "{http://www.w3.org/2000/svg}"


class ProfileCardsTest(unittest.TestCase):
    def test_stats_render_counts_and_green_accents_in_both_themes(self):
        for theme in THEMES.values():
            root = ElementTree.fromstring(stats_card(22502, 38, 23, 4, theme))
            labels = [node.text for node in root.iter(SVG + "text")]
            self.assertEqual(labels[1:3], ["Contributions (Past Year)", "22,502"])
            self.assertEqual(labels[4::2], ["23", "38", "4"])
            self.assertEqual(root.find(SVG + "rect").get("fill"), theme[0])
            self.assertTrue(all(icon.get("stroke") == GREEN for icon in root.iter(SVG + "path")))

    def test_language_bar_includes_smaller_languages_and_escapes_names(self):
        counts = Counter({"A&B": 40, **{letter: 10 for letter in "CDEFGH"}})
        colors = dict.fromkeys(counts, "#8b949e")
        root = ElementTree.fromstring(languages_card(counts, colors, THEMES[""]))
        labels = [node.text for node in root.iter(SVG + "text")]
        self.assertIn("A&B 40.0%", labels)
        self.assertIn("Other 20.0%", labels)
        self.assertAlmostEqual(sum(float(rect.get("width")) for rect in
                                   root.findall(f"{SVG}g/{SVG}rect")), 346)
