"""Audit pre-outcome issued forecasts after a fixed target has matured.

This is deliberately separate from the 126/252-day historical joint-indicator
experiments. It fails closed for incomplete full cohorts and never writes live
forecasts, rankings, UI files, or production model state.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import subprocess
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "research/joint-indicator/prospective-observation-v1"


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git_bytes(commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def direction(value: float) -> int:
    return 1 if value > 0.02 else -1 if value < -0.02 else 0


def sessions_after(origin: str, target: str) -> list[str]:
    start, end = date.fromisoformat(origin), date.fromisoformat(target)
    out = []
    day = start + timedelta(days=1)
    while day <= end:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def percentile(values: list[float], p: float) -> float:
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)]


def metric(rows: list[dict], method: str, probability: bool = False) -> dict:
    selected = [row["methods"][method] for row in rows]
    actual = [row["actualDirection"] for row in rows]
    predicted = [item["direction"] for item in selected]

    def recall(label: int):
        count = sum(value == label for value in actual)
        return sum(a == label and p == label for a, p in zip(actual, predicted)) / count if count else None

    recalls = [recall(label) for label in (-1, 0, 1)]
    down_warnings = sum(value == -1 for value in predicted)
    mapes = [item["mape"] for item in selected]
    errors = [item["returnError"] for item in selected]
    result = {
        "n": len(rows),
        "dates": 1,
        "mape": sum(mapes) / len(mapes),
        "returnMae": sum(errors) / len(errors),
        "p90Mape": percentile(mapes, 0.9),
        "p90ReturnError": percentile(errors, 0.9),
        "directionAccuracy": sum(a == p for a, p in zip(actual, predicted)) / len(rows),
        "balancedDirectionAccuracy": sum(value for value in recalls if value is not None) / sum(value is not None for value in recalls),
        "upRecall": recall(1),
        "downRecall": recall(-1),
        "flatRecall": recall(0),
        "downPrecision": (sum(a == -1 and p == -1 for a, p in zip(actual, predicted)) / down_warnings
                          if down_warnings else None),
        "falseDownWarningRate": sum(a != -1 and p == -1 for a, p in zip(actual, predicted)) / len(rows),
        "directionCounts": {str(k): v for k, v in sorted(Counter(predicted).items())},
        "actualDirectionCounts": {str(k): v for k, v in sorted(Counter(actual).items())},
        "rangeCoverage": (sum(bool(item.get("rangeHit")) for item in selected) / len(rows)
                          if all("rangeHit" in item for item in selected) else None),
        "abstentionRate": 0.0,
    }
    if probability:
        result["brier"] = sum(item["brier"] for item in selected) / len(rows)
        result["logLoss"] = sum(item["logLoss"] for item in selected) / len(rows)
    else:
        result["brier"] = result["logLoss"] = None
    return result


def direction_metric(rows: list[dict], field: str) -> dict:
    actual = [row["actualDirection"] for row in rows]
    predicted = [row["methods"]["v5HorizonModel"][field] for row in rows]

    def recall(label: int):
        count = sum(value == label for value in actual)
        return sum(a == label and p == label for a, p in zip(actual, predicted)) / count if count else None

    recalls = [recall(label) for label in (-1, 0, 1)]
    down_warnings = sum(value == -1 for value in predicted)
    return {
        "n": len(rows), "dates": 1,
        "directionAccuracy": sum(a == p for a, p in zip(actual, predicted)) / len(rows),
        "balancedDirectionAccuracy": sum(value for value in recalls if value is not None) / sum(value is not None for value in recalls),
        "upRecall": recall(1), "downRecall": recall(-1), "flatRecall": recall(0),
        "downPrecision": (sum(a == -1 and p == -1 for a, p in zip(actual, predicted)) / down_warnings
                          if down_warnings else None),
        "falseDownWarningRate": sum(a != -1 and p == -1 for a, p in zip(actual, predicted)) / len(rows),
        "directionCounts": {str(k): v for k, v in sorted(Counter(predicted).items())},
        "actualDirectionCounts": {str(k): v for k, v in sorted(Counter(actual).items())},
        "numericMetricsApplicable": False,
    }


def method_row(anchor: float, point: float, target: float, bounds=None, scores=None) -> dict:
    actual_return = target / anchor - 1
    predicted_return = point / anchor - 1
    result = {
        "value": point,
        "predictedReturn": predicted_return,
        "direction": direction(predicted_return),
        "mape": abs(point / target - 1),
        "returnError": abs(predicted_return - actual_return),
    }
    if bounds:
        result["rangeHit"] = bounds[0] <= target <= bounds[1]
    if scores:
        probs = [float(scores[key]) for key in ("down", "flat", "up")]
        label = direction(actual_return) + 1
        result["brier"] = sum((prob - (index == label)) ** 2 for index, prob in enumerate(probs)) / 3
        result["logLoss"] = -math.log(max(probs[label], 1e-15))
        result["classifierRawArgmax"] = (-1, 0, 1)[max(range(3), key=lambda index: probs[index])]
        result["classifierStoredChosen"] = int(scores["chosen"])
    return result


def build(output: Path = FOLDER) -> dict:
    protocol_raw = (FOLDER / "PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_raw)
    commit = protocol["sourceMainCommit"]
    raw = {}
    for name, source in protocol["inputs"].items():
        value = git_bytes(commit, source["path"])
        if digest(value) != source["sha256"]:
            raise ValueError(f"{name} source hash changed")
        raw[name] = value

    issued = json.loads(raw["issued"])
    targets_doc = json.loads(raw["targetPrices"])
    targets = {symbol: float(row["price"]) for symbol, row in targets_doc["stocks"].items()
               if row.get("asOf") == protocol["observation"]["targetDate"]}
    trend = list(csv.DictReader(io.StringIO(raw["simpleTrend"].decode())))
    observation = protocol["observation"]
    origin, target_date = observation["origin"], observation["targetDate"]
    sessions = sessions_after(origin, target_date)
    if len(sessions) != observation["horizonSessions"] or sessions[-1] != target_date:
        raise ValueError("Fixed target is not the expected 21st XNYS weekday session")

    models = observation["models"]
    model_rows = {}
    for model in models:
        rows = [row for row in issued if row.get("model") == model and row.get("asOf") == origin
                and str(row.get("horizon")) == "21"]
        if len(rows) != len({row["symbol"] for row in rows}):
            raise ValueError(f"Duplicate symbol in {model}")
        if any(row["issuedAt"][:10] >= target_date for row in rows):
            raise ValueError(f"Post-target issuance in {model}")
        model_rows[model] = {row["symbol"]: row for row in rows}

    full_symbols = sorted(model_rows[models[-1]])
    missing_full = sorted(set(full_symbols) - set(targets))
    common = sorted(set.intersection(*(set(model_rows[model]) for model in models), set(targets)))
    trend_rows = {(row["symbol"], row["asOf"], row["horizon"]): row for row in trend
                  if row.get("model") == "trend-decay-v1"}
    if any((symbol, origin, "21") not in trend_rows for symbol in common):
        raise ValueError("Simple-trend control missing from common cohort")

    rows = []
    for symbol in common:
        target = targets[symbol]
        source = {model: model_rows[model][symbol] for model in models}
        anchor = float(source[models[0]]["anchor"])
        actual_return = target / anchor - 1
        one = {
            "symbol": symbol,
            "origin": origin,
            "targetDate": target_date,
            "targetPrice": target,
            "actualReturn": actual_return,
            "actualDirection": direction(actual_return),
            "methods": {},
        }
        one["methods"]["noChange"] = method_row(anchor, anchor, target)
        tr = trend_rows[(symbol, origin, "21")]
        one["methods"]["simpleTrend"] = method_row(float(tr["anchor"]), float(tr["base"]), target,
                                                      (float(tr["bear"]), float(tr["bull"])))
        for label, model, field in (
            ("v2Balanced", models[0], "balanced"),
            ("v3Balanced", models[1], "balanced"),
            ("v4Balanced", models[2], "balanced"),
            ("v5Balanced", models[3], "balanced"),
            ("v5HorizonModel", models[3], "horizonModel"),
        ):
            item = source[model]
            bounds = (float(item["range"]["low"]), float(item["range"]["high"]))
            one["methods"][label] = method_row(float(item["anchor"]), float(item[field]), target, bounds,
                                                 item.get("horizonDirectionScores") if label == "v5HorizonModel" else None)
        rows.append(one)

    numeric = ["noChange", "simpleTrend", "v2Balanced", "v3Balanced", "v4Balanced", "v5Balanced", "v5HorizonModel"]
    evaluation = {name: metric(rows, name, name == "v5HorizonModel") for name in numeric}
    evaluation["v5ClassifierRawArgmax"] = direction_metric(rows, "classifierRawArgmax")
    evaluation["v5ClassifierStoredChosen"] = direction_metric(rows, "classifierStoredChosen")
    actual_counts = evaluation["noChange"]["actualDirectionCounts"]
    always_up = {
        "n": len(rows), "dates": 1, "directionAccuracy": int(actual_counts.get("1", 0)) / len(rows),
        "balancedDirectionAccuracy": 1 / 3, "upRecall": 1.0, "downRecall": 0.0, "flatRecall": 0.0,
        "downPrecision": None, "falseDownWarningRate": 0.0, "directionCounts": {"1": len(rows)},
        "actualDirectionCounts": actual_counts, "numericMetricsApplicable": False,
    }
    evaluation["alwaysUp"] = always_up

    horizon_counts = {str(h): sum(str(row.get("horizon")) == str(h) for row in issued) for h in (126, 252)}
    result = {
        "version": protocol["version"],
        "registeredAt": protocol["registeredAt"],
        "sourceMainCommit": commit,
        "protocolHash": digest(protocol_raw),
        "inputHashes": {name: source["sha256"] for name, source in protocol["inputs"].items()},
        "observation": {"origin": origin, "targetDate": target_date, "sessions": sessions},
        "longHorizonReadiness": {
            "issuedRows": horizon_counts,
            "maturedRows": {"126": 0, "252": 0},
            "scoredRows": {"126": 0, "252": 0},
            "reason": "Earliest long-horizon origin has not reached 126 or 252 XNYS sessions by the fixed target archive."
        },
        "fullCohort": {
            "issued": len(full_symbols), "targetAvailable": len(full_symbols) - len(missing_full),
            "missing": len(missing_full), "missingSymbols": missing_full,
            "coverage": (len(full_symbols) - len(missing_full)) / len(full_symbols),
            "aggregateMetricsAllowed": False,
            "reason": "Incomplete fixed target source; survivor-only aggregate is prohibited."
        },
        "commonCohort": {"n": len(common), "symbols": common, "dates": 1, "abstained": 0},
        "evaluation": evaluation,
        "hypothesisChecks": {
            "A": {
                "magnitudeBetterThanNoChange": evaluation["v5HorizonModel"]["mape"] < evaluation["noChange"]["mape"]
                                                   and evaluation["v5HorizonModel"]["returnMae"] < evaluation["noChange"]["returnMae"],
                "directionNoWorseThanTrend": evaluation["v5HorizonModel"]["balancedDirectionAccuracy"] >= evaluation["simpleTrend"]["balancedDirectionAccuracy"],
                "passed": False
            },
            "B": {
                "downsideLift": evaluation["v5ClassifierRawArgmax"]["downRecall"] > evaluation["v2Balanced"]["downRecall"],
                "balancedDirectionLift": evaluation["v5ClassifierRawArgmax"]["balancedDirectionAccuracy"] > evaluation["v2Balanced"]["balancedDirectionAccuracy"],
                "passed": False
            }
        },
        "selection": None,
        "prospectiveStatus": "Underlying forecasts were issued before outcomes. The common-cohort audit protocol is post-target and one-date, so results are observational and non-promotable.",
        "blendEvaluation": "not_run_post_target_design_would_be_diagnostic_only",
        "uiChanged": False,
        "serviceForecastChanged": False,
        "tradeClaims": False,
        "rows": rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_bytes(canonical(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=FOLDER)
    args = parser.parse_args()
    built = build(args.output)
    print(json.dumps({
        "common": built["commonCohort"]["n"],
        "fullCoverage": built["fullCohort"]["coverage"],
        "longMatured": built["longHorizonReadiness"]["maturedRows"],
        "selected": built["selection"],
    }, sort_keys=True))
