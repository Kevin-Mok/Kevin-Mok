import importlib.util
import pathlib
import re
import unittest
from datetime import date


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_contribution_graph.py"

spec = importlib.util.spec_from_file_location("generate_contribution_graph", MODULE_PATH)
graph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(graph)


class GenerateContributionGraphTests(unittest.TestCase):
    def _segment_endpoints(self, path: str) -> list[tuple[float, float]]:
        tokens = path.split()
        endpoints: list[tuple[float, float]] = []
        index = 0
        while index < len(tokens):
            command = tokens[index]
            if command == "M":
                endpoints.append((float(tokens[index + 1]), float(tokens[index + 2])))
                index += 3
                continue
            if command == "Q":
                endpoints.append((float(tokens[index + 3]), float(tokens[index + 4])))
                index += 5
                continue
            if command == "C":
                endpoints.append((float(tokens[index + 5]), float(tokens[index + 6])))
                index += 7
                continue
            self.fail(f"Unexpected path command: {command}")
        return endpoints

    def test_curve_passes_through_all_points(self) -> None:
        scenarios = {
            "flat_run_then_spike": [
                (0.0, 12.0),
                (10.0, 6.0),
                (20.0, 20.0),
                (30.0, 4.0),
                (40.0, 14.0),
            ],
            "zeros_and_small_oscillations": [
                (0.0, 8.0),
                (10.0, 0.0),
                (20.0, 0.0),
                (30.0, 3.0),
                (40.0, 1.0),
                (50.0, 5.0),
            ],
            "plateau": [
                (0.0, 4.0),
                (10.0, 4.0),
                (20.0, 4.0),
                (30.0, 10.0),
            ],
            "two_points": [
                (0.0, 2.0),
                (10.0, 12.0),
            ],
        }

        for name, points in scenarios.items():
            with self.subTest(name=name):
                path = graph.build_smooth_path(points)
                self.assertEqual(self._segment_endpoints(path), points)

    def test_svg_line_endpoints_match_circle_positions(self) -> None:
        counts_by_day = {
            date(2026, 1, 1): 3,
            date(2026, 1, 2): 0,
            date(2026, 1, 3): 11,
            date(2026, 1, 4): 2,
            date(2026, 1, 5): 8,
        }

        svg = graph.build_svg(
            "Kevin-Mok",
            date(2026, 1, 1),
            date(2026, 1, 5),
            counts_by_day,
        )

        line_match = re.search(r'<path d="([^"]+)" class="line" />', svg)
        self.assertIsNotNone(line_match)
        circle_matches = re.findall(
            r'<circle cx="([0-9.]+)" cy="([0-9.]+)" r="4.5" class="point" />',
            svg,
        )
        self.assertTrue(circle_matches)

        endpoints = self._segment_endpoints(line_match.group(1))
        circles = [(float(x), float(y)) for x, y in circle_matches]
        self.assertEqual(endpoints, circles)


if __name__ == "__main__":
    unittest.main()
