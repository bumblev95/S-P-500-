import gzip
import hashlib
import json
import unittest
from pathlib import Path

import numpy as np

from research_rank_tilt import FOLDER, average_percentile, candidate_rows, rank_features


class RankTiltTests(unittest.TestCase):
    def test_average_percentile_uses_mid_ranks(self):
        actual = average_percentile([3.0, 1.0, 1.0, 2.0])
        np.testing.assert_allclose(actual, [0.875, 0.25, 0.25, 0.625])

    def test_cross_section_rank_and_sparse_rule_are_target_free(self):
        rows = []
        features = {}
        for index, symbol in enumerate(("A", "B", "C", "D", "E")):
            rows.append({
                "symbol": symbol, "origin": "2024-01-02", "targetDate": "2024-07-01",
                "y": 0.5 + index, "methods": {"priceOnly": {"value": 1.0, "direction": 0}}
            })
            relative = [0.0] * 11
            relative[9] = relative[10] = float(index)
            absolute = [0.0] * 14
            absolute[4] = -0.1
            features[f"{symbol}|2024-01-02"] = {
                "usable": True, "relative": relative, "absolute": absolute
            }
        ranked = rank_features(rows, features)
        self.assertAlmostEqual(ranked["A|2024-01-02"]["percentile"], 0.1)
        self.assertAlmostEqual(ranked["E|2024-01-02"]["percentile"], 0.9)
        first, coverage = candidate_rows(rows, features)
        changed = [r for r in first if r["methods"]["sparse_down_tilt"]["value"] != 1.0]
        self.assertEqual([r["symbol"] for r in changed], ["A"])
        self.assertEqual(coverage["sparseAdjustedRows"], 1)
        for row in rows:
            row["y"] *= 100
        second, _ = candidate_rows(rows, features)
        self.assertEqual(
            [r["methods"]["symmetric_rank_tilt"]["value"] for r in first],
            [r["methods"]["symmetric_rank_tilt"]["value"] for r in second],
        )

    def test_registered_input_hashes_match(self):
        protocol = json.loads((FOLDER / "PROTOCOL.json").read_text())
        for field, relative_path in (
            ("pairedPredictionsSha256", protocol["inputs"]["pairedPredictions"]),
            ("featureSnapshotSha256", protocol["inputs"]["featureSnapshot"]),
            ("relativeResultsSha256", "../relative-v1/results.json"),
        ):
            data = (FOLDER / relative_path).resolve().read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), protocol["inputs"][field])

    def test_saved_predictions_have_every_source_row(self):
        source = json.loads(gzip.decompress(
            (FOLDER / "../relative-v1/predictions.json.gz").resolve().read_bytes()
        ))
        saved = json.loads(gzip.decompress((FOLDER / "predictions.json.gz").read_bytes()))
        for horizon in ("126", "252"):
            self.assertEqual(
                len(saved[horizon]["pairedEvaluation"]),
                len(source[horizon]["pairedEvaluation"]),
            )


if __name__ == "__main__":
    unittest.main()
