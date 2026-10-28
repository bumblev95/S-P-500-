import copy
import gzip
import hashlib
import json
import unittest
from datetime import date, timedelta

import numpy as np

from collect_momentum_decomposition import decompose
from research_momentum_decomposition import FOLDER, average_percentile, build_rows, ranked_features


class MomentumDecompositionTests(unittest.TestCase):
    def test_average_percentile_uses_mid_ranks(self):
        np.testing.assert_allclose(
            average_percentile([3.0, 1.0, 1.0, 2.0]),
            [0.875, 0.25, 0.25, 0.625],
        )

    def test_components_add_and_do_not_read_origin_or_future(self):
        first = date(2020, 1, 1)
        series = [
            ((first + timedelta(days=index)).isoformat(), float(100 + index + 5 * np.sin(index)))
            for index in range(270)
        ]
        origin = (first + timedelta(days=260)).isoformat()
        expected = decompose(series, origin)
        poisoned = copy.deepcopy(series)
        poisoned[260:] = [(day, value * 1000) for day, value in poisoned[260:]]
        actual = decompose(poisoned, origin)
        self.assertEqual(expected, actual)
        self.assertLess(expected["through"], origin)
        self.assertAlmostEqual(expected["htp"] + expected["pth"], expected["totalMomentum"])

    def test_sparse_guard_requires_both_top_quintiles_and_is_target_free(self):
        origin = "2024-01-02"
        rows = []
        features = {}
        for index, symbol in enumerate(("A", "B", "C", "D", "E")):
            rows.append({
                "symbol": symbol, "origin": origin, "targetDate": "2024-07-01",
                "y": 0.5 + index, "regime": "test", "priceOnly": 1.0,
            })
            htp = float(index)
            pth = float(index) / 10
            features[f"{symbol}|{origin}"] = {
                "usable": True, "htp": htp, "pth": pth,
                "totalMomentum": htp + pth, "trailing126": 0.0,
            }
        ranks = ranked_features(rows, features)
        self.assertAlmostEqual(ranks[f"E|{origin}"]["htpPercentile"], 0.9)
        built, coverage = build_rows(rows, features, 126)
        guarded = [row["symbol"] for row in built if row["hypeGuarded"]]
        self.assertEqual(guarded, ["E"])
        self.assertEqual(coverage["hypeGuardRows"], 1)
        forecasts = [row["methods"]["pth_hype_guard"]["value"] for row in built]
        for row in rows:
            row["y"] *= 100
        rebuilt, _ = build_rows(rows, features, 126)
        self.assertEqual(
            forecasts,
            [row["methods"]["pth_hype_guard"]["value"] for row in rebuilt],
        )

    def test_registered_sources_and_collection_order_match(self):
        protocol_raw = (FOLDER / "PROTOCOL.json").read_bytes()
        protocol = json.loads(protocol_raw)
        environment_raw = gzip.decompress(
            (FOLDER / protocol["source"]["environment"]).read_bytes()
        )
        universe_raw = (FOLDER / protocol["source"]["universe"]).read_bytes()
        snapshot = json.loads(gzip.decompress((FOLDER / "sources/features.json.gz").read_bytes()))
        self.assertEqual(hashlib.sha256(environment_raw).hexdigest(), protocol["source"]["environmentSha256"])
        self.assertEqual(hashlib.sha256(universe_raw).hexdigest(), protocol["source"]["universeSha256"])
        self.assertEqual(snapshot["protocolHash"], hashlib.sha256(protocol_raw).hexdigest())
        self.assertGreater(snapshot["collectedAt"], protocol["registeredAt"])

    def test_saved_result_retains_all_rows_and_no_candidate_passes(self):
        result = json.loads((FOLDER / "results.json").read_text())
        saved = json.loads(gzip.decompress((FOLDER / "predictions.json.gz").read_bytes()))
        expected = {"126": 4408, "252": 3855}
        for horizon, count in expected.items():
            self.assertEqual(result["horizons"][horizon]["coverage"]["totalRows"], count)
            self.assertEqual(len(saved[horizon]["pairedEvaluation"]), count)
            self.assertFalse(any(result["horizons"][horizon]["passed"].values()))
            self.assertEqual(result["horizons"][horizon]["diagnostics"]["abstentionFraction"], 0.0)


if __name__ == "__main__":
    unittest.main()
