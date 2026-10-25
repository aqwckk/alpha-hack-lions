"""Fast regression checks for discrimination metrics at score thresholds."""

import unittest
from itertools import permutations

from src.model import gini_ks


class GiniKsTests(unittest.TestCase):
    def test_ties_and_separation_are_order_invariant(self):
        cases = [
            ("constant", [1, 0, 1, 0], [100, 100, 100, 100], (0.5, 0.0, 0.0)),
            ("balanced_ties", [1, 0, 1, 0], [100, 100, 200, 200], (0.5, 0.0, 0.0)),
            ("partial_ties", [1, 0, 1, 0], [100, 100, 200, 300], (0.625, 0.25, 0.5)),
            ("separated_ties", [1, 1, 0, 0], [100, 100, 200, 200], (1.0, 1.0, 1.0)),
            ("separated", [1, 1, 0, 0], [100, 200, 300, 400], (1.0, 1.0, 1.0)),
            ("reversed", [1, 1, 0, 0], [400, 300, 200, 100], (0.0, -1.0, 1.0)),
        ]
        for name, labels, scores, expected in cases:
            for rows in sorted(set(permutations(zip(labels, scores)))):
                with self.subTest(case=name, rows=rows):
                    y, score = zip(*rows)
                    for actual, target in zip(gini_ks(y, score), expected):
                        self.assertAlmostEqual(actual, target)


if __name__ == "__main__":
    unittest.main()
