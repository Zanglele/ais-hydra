"""Focused checks for the joint-window extension and boundary preservation."""
import unittest

import numpy as np

from run_pipeline import build_windows, route_descriptor, score_joint_windows, candidate_rows, HYDRA


class PipelineChecks(unittest.TestCase):
    def test_export_coordinates_times_and_overlap_deduplication(self):
        record = dict(mmsi=123, anomaly_label=0, timestamp=[120 * j for j in range(9)],
                      lat=[70 + j / 10 for j in range(9)], lon=list(range(9)),
                      speed=[10] * 9, course=[90] * 9)
        windows, points = candidate_rows("test", record, 2, np.array([0, 2, 4]),
                                        np.array([4., 6., 1.]), np.array([.98, .99, .5]),
                                        np.array([True, True, False]), 3., 4)
        self.assertEqual(len(windows), 2)
        self.assertEqual([r["original_point_index"] for r in points], [1, 2, 3, 4, 5, 6])
        self.assertEqual(points[2]["covering_candidate_windows"], 2)
        self.assertEqual(points[2]["max_covering_window_score"], 6.)
        self.assertEqual(points[0]["latitude"], record["lat"][1])
        self.assertEqual(points[-1]["longitude"], record["lon"][6])
        self.assertEqual(windows[-1]["end_latitude"], record["lat"][6])
        self.assertEqual(points[0]["time_utc"], "1970-01-01T00:02:00+00:00")
        self.assertEqual(points[0]["time_beijing"], "1970-01-01T08:02:00+08:00")
        self.assertEqual(candidate_rows("test", record, 2, np.array([0]), np.array([0.]),
                                        np.array([.5]), np.array([False]), 0., 4), ([], []))

    def test_windows_never_cross_trajectory_boundary(self):
        a = np.arange(21, dtype=float).reshape(7, 3)
        b = a + 1000
        aw, starts = build_windows(a, 4, 2)
        bw, _ = build_windows(b, 4, 2)
        self.assertEqual(starts.tolist(), [0, 2, 3])
        self.assertTrue((aw < 1000).all())
        self.assertTrue((bw >= 1000).all())
        np.testing.assert_array_equal(aw[-1], a[3:7].T.ravel())

    def test_single_series_matches_upstream_window_ensemble(self):
        x = np.random.default_rng(9).normal(size=(70, 3))
        reference = HYDRA(10, mode="approx", ann_backend="sklearn", random_state=42)
        reference.compress_and_score_multi(x)
        _, expected = reference.ensemble_maxpool_windows()
        scaled = (x - x.mean(axis=0)) / x.std(axis=0)
        windows, _ = build_windows(scaled, 10, 1)
        actual, _, backend = score_joint_windows(windows, 10, "sklearn", 42)
        self.assertEqual(backend, "sklearn")
        np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-5)

    def test_route_descriptor_preserves_location_and_direction(self):
        a = {"lat": np.array([77., 78., 79.]), "lon": np.array([10., 11., 12.])}
        reverse = {k: v[::-1] for k, v in a.items()}
        elsewhere = {"lat": a["lat"], "lon": a["lon"] + 10}
        self.assertFalse(np.allclose(route_descriptor(a), route_descriptor(reverse)))
        self.assertFalse(np.allclose(route_descriptor(a), route_descriptor(elsewhere)))


if __name__ == "__main__":
    unittest.main()
