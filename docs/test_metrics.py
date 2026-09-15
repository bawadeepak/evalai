"""Analytic examples and exhaustive finite-pool checks, no LLM calls."""

import itertools
import math
import unittest

import metrics as m


class MetricsTests(unittest.TestCase):
    def test_video_gaps_and_missing_slice_weights(self):
        for value in m.accuracy_gaps(.90, .89, .88, .87).values():
            self.assertAlmostEqual(value, .01)
        self.assertAlmostEqual(m.weighted_mean([.95, .9, .85, .17], [1, 1, 1, 1]), .7175)
        self.assertAlmostEqual(m.weighted_mean([.2, .8], [1, 3]), .65)

    def test_wilson_reference_and_boundary_behavior(self):
        low, high = m.wilson_interval(18, 20)
        self.assertAlmostEqual(low, .6989663548, places=8)
        self.assertAlmostEqual(high, .9721335188, places=8)
        self.assertAlmostEqual(m.wilson_interval(0, 100)[0], 0)
        self.assertAlmostEqual(m.wilson_interval(100, 100)[1], 1)
        self.assertLess(m.wilson_interval(100, 100)[0], 1)

    def test_wilson_complement_symmetry_and_narrowing(self):
        for n in range(1, 20):
            for c in range(n + 1):
                low, high = m.wilson_interval(c, n)
                other_low, other_high = m.wilson_interval(n - c, n)
                self.assertAlmostEqual(low, 1 - other_high)
                self.assertAlmostEqual(high, 1 - other_low)
        a, b = m.wilson_interval(9, 10)
        c, d = m.wilson_interval(90, 100)
        self.assertLess(d - c, b - a)

    def test_zero_failure_bound_sample_size(self):
        self.assertAlmostEqual(m.zero_failure_upper_bound(100), .0295130496, places=9)
        self.assertGreater(m.zero_failure_upper_bound(298), .01)
        self.assertLess(m.zero_failure_upper_bound(299), .01)

    def test_beta_prior_is_explicit(self):
        self.assertAlmostEqual(m.beta_posterior_mean(8, 10), 9 / 12)
        self.assertAlmostEqual(m.beta_posterior_mean(8, 10, .5, .5), 8.5 / 11)

    def test_repeatability_by_explicit_pairs(self):
        outputs = ["A"] * 6 + ["B"] * 4
        pairs = list(itertools.combinations(outputs, 2))
        result = m.repeatability(outputs)
        self.assertEqual(result["modal_agreement"], .6)
        self.assertAlmostEqual(result["pairwise_agreement"], sum(a == b for a, b in pairs) / len(pairs))
        self.assertEqual(m.repeatability(["a", "a"])["entropy_nats"], 0)
        self.assertIsNone(m.repeatability(["a"])["pairwise_agreement"])
        self.assertIsNone(m.repeatability(["a"])["entropy_nats"])

    def test_pass_estimators_against_all_subsets(self):
        for n in range(1, 9):
            for c in range(n + 1):
                pool = [True] * c + [False] * (n - c)
                for k in range(1, n + 1):
                    subsets = list(itertools.combinations(pool, k))
                    self.assertAlmostEqual(m.pass_at_k(c, n, k), sum(any(s) for s in subsets) / len(subsets))
                    self.assertAlmostEqual(m.pass_all_k(c, n, k), sum(all(s) for s in subsets) / len(subsets))

    def test_probability_scores_known_answers(self):
        self.assertEqual(m.brier_score([0, 1], [0, 1]), 0)
        self.assertEqual(m.brier_score([1, 0], [0, 1]), 1)
        self.assertEqual(m.brier_score([.5, .5], [0, 1]), .25)
        self.assertAlmostEqual(m.binary_log_loss([.5, .5], [0, 1]), math.log(2))
        self.assertGreater(m.binary_log_loss([1, 0], [0, 1]), 30)
        self.assertTrue(math.isfinite(m.binary_log_loss([1, 0], [0, 1])))

    def test_calibration_bin_boundaries_and_undefined_bins(self):
        result = m.calibration_bins([0, .5, 1], [0, 0, 1], bins=2)
        self.assertEqual([b["count"] for b in result["bins"]], [1, 2])
        self.assertAlmostEqual(result["ece"], 1 / 6)
        result = m.calibration_bins([.2] * 5, [0, 0, 0, 0, 1], bins=5)
        self.assertEqual(result["ece"], 0)
        self.assertIsNone(result["bins"][0]["outcome"])

    def test_selective_risk_threshold_and_empty_selection(self):
        result = m.selective_risk([.9, .8, .4], [1, 0, 1], .8)
        self.assertEqual(result["accepted"], 2)
        self.assertAlmostEqual(result["coverage"], 2 / 3)
        self.assertEqual(result["risk"], .5)
        self.assertIsNone(m.selective_risk([.2], [1], .9)["risk"])

    def test_paired_bootstrap_preserves_pairing(self):
        baseline = [0, 1, 0, 1]
        identical = m.paired_delta_interval(baseline, baseline, resamples=200)
        self.assertEqual((identical["lower"], identical["delta"], identical["upper"]), (0, 0, 0))
        self.assertTrue(identical["degenerate"])
        first = m.paired_delta_interval([0, 0, 1, 1], [1, 0, 1, 1], resamples=200)
        second = m.paired_delta_interval([0, 0, 1, 1], [1, 0, 1, 1], resamples=200)
        self.assertEqual(first, second)
        self.assertEqual(first["delta"], .25)
        self.assertGreaterEqual(first["lower"], 0)
        self.assertLessEqual(first["upper"], 1)

    def test_invalid_and_missing_inputs_are_not_silent_scores(self):
        bad_calls = [
            lambda: m.wilson_interval(0, 0), lambda: m.wilson_interval(3, 2),
            lambda: m.wilson_interval(True, 2), lambda: m.wilson_interval(1, 2, 1),
            lambda: m.brier_score([], []), lambda: m.brier_score([.2], []),
            lambda: m.brier_score([float("nan")], [1]), lambda: m.brier_score([.2], [2]),
            lambda: m.binary_log_loss([.2], [1], 0), lambda: m.pass_at_k(1, 2, 3),
            lambda: m.pass_all_k(1, 2, 0), lambda: m.repeatability([]),
            lambda: m.weighted_mean([1], [0]), lambda: m.weighted_mean([1], [-1]),
            lambda: m.beta_posterior_mean(1, 2, 0, 1),
            lambda: m.calibration_bins([.2], [0], 0),
            lambda: m.paired_delta_interval([1], [1]),
            lambda: m.selective_risk([.2], [1], 1.1),
        ]
        for call in bad_calls:
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()


if __name__ == "__main__":
    unittest.main()
