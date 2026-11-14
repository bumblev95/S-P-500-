"""Evaluate registered endpoint-direction versus within-horizon drawdown hypotheses."""
import argparse
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "research/joint-indicator/drawdown-separation-v1"
WARNING_NAMES = {
    "terminalForecast": "종료 하락 예측(기준)",
    "trailingDrawdown": "직전 63일 -20% 낙폭",
    "trendBreak": "200일선 하회+63일 약세",
    "roleUnion": "종료 예측 또는 추세 이탈",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_path_snapshot(folder):
    source_folder = folder / "sources"
    manifest = json.loads((source_folder / "path-snapshot.manifest.json").read_text())
    chunks = []
    for part in manifest["parts"]:
        data = (source_folder / part["name"]).read_bytes()
        if len(data) != part["size"] or digest(data) != part["sha256"]:
            raise ValueError("Path snapshot chunk mismatch: " + part["name"])
        chunks.append(data)
    compressed = b"".join(chunks)
    if len(compressed) != manifest["gzipSize"] or digest(compressed) != manifest["gzipSha256"]:
        raise ValueError("Reassembled path snapshot mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != manifest["rawSize"] or digest(raw) != manifest["rawSha256"]:
        raise ValueError("Decompressed path snapshot mismatch")
    return compressed, json.loads(raw)


def date_weights(rows):
    counts = Counter(row["origin"] for row in rows)
    return np.array([1.0 / counts[row["origin"]] for row in rows], dtype=float)


def direction(values):
    values = np.asarray(values)
    return np.where(values > 1.02, 1, np.where(values < 0.98, -1, 0))


def weighted_quantile(values, weights, quantile):
    values, weights = np.asarray(values), np.asarray(weights)
    order = np.argsort(values, kind="stable")
    mass = np.cumsum(weights[order]) / weights.sum()
    return float(values[order[min(np.searchsorted(mass, quantile), len(order) - 1)]])


def maximum_drawdown(ratios):
    values = np.asarray(ratios, dtype=float)
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1.0))


def risk_metrics(rows, name):
    if not rows:
        return None
    weights = date_weights(rows)
    target = np.array([row["severeDrawdown"] for row in rows], dtype=bool)
    warning = np.array([row["warnings"][name] for row in rows], dtype=bool)
    average = lambda values, w=weights: float(np.average(values, weights=w))
    severe, not_severe = target, ~target
    by_date = {}
    for day in sorted({row["origin"] for row in rows}):
        subset = [row for row in rows if row["origin"] == day]
        y = np.array([row["severeDrawdown"] for row in subset], dtype=bool)
        p = np.array([row["warnings"][name] for row in subset], dtype=bool)
        by_date[day] = {
            "rows": len(subset),
            "prevalence": float(y.mean()),
            "warningRate": float(p.mean()),
            "recall": float(p[y].mean()) if y.any() else None,
            "precision": float(y[p].mean()) if p.any() else None,
            "falseWarningRate": float(p[~y].mean()) if (~y).any() else None,
        }
    return {
        "rows": len(rows),
        "metricWeighting": "Equal total weight per origin date",
        "prevalence": average(target),
        "warningRate": average(warning),
        "recall": average(warning[severe], weights[severe]) if severe.any() else None,
        "precision": average(target[warning], weights[warning]) if warning.any() else None,
        "falseWarningRate": average(warning[not_severe], weights[not_severe]) if not_severe.any() else None,
        "balancedAccuracy": float(np.mean([
            average(warning[severe], weights[severe]) if severe.any() else np.nan,
            average(~warning[not_severe], weights[not_severe]) if not_severe.any() else np.nan,
        ])),
        "pooledAllRows": {
            "prevalence": float(target.mean()),
            "warningRate": float(warning.mean()),
            "recall": float(warning[severe].mean()) if severe.any() else None,
            "precision": float(target[warning].mean()) if warning.any() else None,
            "falseWarningRate": float(warning[not_severe].mean()) if not_severe.any() else None,
        },
        "byDate": by_date,
    }


def endpoint_metrics(rows):
    weights = date_weights(rows)
    actual = np.array([row["y"] for row in rows])
    predicted = np.array([row["priceOnly"] for row in rows])
    truth, guess = direction(actual), direction(predicted)
    average = lambda values, w=weights: float(np.average(values, weights=w))
    recalls = {str(c): average(guess[truth == c] == c, weights[truth == c]) if np.any(truth == c) else None for c in (-1, 0, 1)}
    down = guess == -1
    not_down = truth != -1
    return {
        "mape": average(abs(predicted / actual - 1)),
        "returnMae": average(abs(predicted - actual)),
        "p90Mape": weighted_quantile(abs(predicted / actual - 1), weights, 0.9),
        "p90ReturnError": weighted_quantile(abs(predicted - actual), weights, 0.9),
        "directionAccuracy": average(guess == truth),
        "balancedDirectionAccuracy": float(np.mean([value for value in recalls.values() if value is not None])),
        "upRecall": recalls["1"],
        "downRecall": recalls["-1"],
        "flatRecall": recalls["0"],
        "downPrecision": average(truth[down] == -1, weights[down]) if down.any() else None,
        "falseDownWarningRate": average(down[not_down], weights[not_down]) if not_down.any() else None,
        "alwaysUpAccuracy": average(truth == 1),
        "abstentionFraction": 0.0,
        "probability": {"status": "not_applicable", "brier": None, "logLoss": None},
    }


def validate(protocol, source, features, paths, universe):
    if paths["protocolHash"] != digest(json.dumps(protocol, indent=2, ensure_ascii=False).encode() + b"\n"):
        # Preserve exact file-byte hashing while making the error useful for callers using parsed fixtures.
        protocol_bytes = (FOLDER / "PROTOCOL.json").read_bytes()
        if paths["protocolHash"] != digest(protocol_bytes):
            raise ValueError("Path snapshot was not collected under this protocol")
    if paths["environmentRawHash"] != protocol["sourceHashes"]["environmentRawSha256"]:
        raise ValueError("Environment mismatch")
    for horizon in protocol["horizons"]:
        seen = set()
        all_rows = source["stocks"][str(horizon)]["outcomes"]
        for row in all_rows:
            key = (row["origin"], universe["members"][row["symbol"]]["cik"])
            if key in seen:
                raise ValueError("Duplicate CIK/date")
            seen.add(key)
    for key, path in paths["paths"].items():
        if path["status"] != "ok":
            continue
        if not path["anchorDate"] < path["origin"]:
            raise ValueError(f"Non-past anchor: {key}")
        if path["through"] > path["targetDate"] or max(path["dates"]) > path["targetDate"]:
            raise ValueError(f"Future leakage: {key}")
        if path["dates"][0] != path["anchorDate"] or len(path["dates"]) != len(path["ratios"]):
            raise ValueError(f"Invalid path alignment: {key}")
    if digest(gzip.decompress((FOLDER.parent / "relative-v1/sources/raw-features.json.gz").read_bytes())) != protocol["sourceHashes"]["featureRawSha256"]:
        raise ValueError("Feature snapshot mismatch")
    if features["sourceHash"] != protocol["sourceHashes"]["environmentRawSha256"]:
        raise ValueError("Feature/environment mismatch")


def evaluate(protocol, source, features, paths):
    result = {}
    saved = {}
    for horizon in protocol["horizons"]:
        all_rows = source["stocks"][str(horizon)]["outcomes"]
        dates = sorted({row["origin"] for row in all_rows})
        evaluation_dates = dates[len(dates) // 2:]
        original = [row for row in all_rows if row["origin"] in evaluation_dates]
        records, missing = [], []
        for row in original:
            key = f"{horizon}|{row['symbol']}|{row['origin']}"
            path = paths["paths"].get(key, {"status": "missing", "reason": "absent_key"})
            feature = features["features"][f"{row['symbol']}|{row['origin']}"]
            if path["status"] != "ok":
                missing.append({"symbol": row["symbol"], "origin": row["origin"], "reason": path.get("reason", "fetch_error")})
                continue
            mdd = maximum_drawdown(path["ratios"])
            absolute = feature["absolute"] if feature["usable"] else None
            terminal_warning = row["priceOnly"] < 0.98
            trailing = bool(absolute is not None and absolute[5] <= -0.20)
            trend = bool(absolute is not None and absolute[4] < 0 and absolute[0] < 0)
            records.append({
                "symbol": row["symbol"], "origin": row["origin"], "targetDate": row["targetDate"],
                "regime": row["regime"], "y": row["y"], "priceOnly": row["priceOnly"],
                "pathThrough": path["through"], "pathEndpointRatio": path["ratios"][-1],
                "endpointRatioAbsoluteDifference": abs(path["ratios"][-1] - row["y"]),
                "maximumDrawdown": mdd, "severeDrawdown": mdd <= -0.20,
                "endpointDown": row["y"] < 0.98, "recoveredTerminal": mdd <= -0.20 and row["y"] >= 0.98,
                "inputUsable": feature["usable"],
                "warnings": {
                    "terminalForecast": terminal_warning,
                    "trailingDrawdown": trailing,
                    "trendBreak": trend,
                    "roleUnion": terminal_warning or trend,
                },
            })
        risk = {name: risk_metrics(records, name) for name in WARNING_NAMES}
        severe = [record for record in records if record["severeDrawdown"]]
        recovered = [record for record in severe if record["recoveredTerminal"]]
        terminal = risk["terminalForecast"]
        checks = {}
        for name in ("trailingDrawdown", "trendBreak", "roleUnion"):
            metric = risk[name]
            checks[name] = {
                "pathCoverage": len(records) / len(original) >= protocol["gate"]["minimumPathCoverage"],
                "recallLift": metric["recall"] >= terminal["recall"] + protocol["gate"]["minimumSevereRecallLift"],
                "precisionLift": metric["precision"] is not None and metric["precision"] >= metric["prevalence"] + protocol["gate"]["minimumSeverePrecisionLiftOverPrevalence"],
                "falseWarnings": metric["falseWarningRate"] <= terminal["falseWarningRate"] + protocol["gate"]["maximumFalseWarningRateIncreaseVsTerminal"],
                "precisionVsTerminal": metric["precision"] is not None and metric["precision"] >= terminal["precision"],
                "noFalseWarningIncrease": metric["falseWarningRate"] <= terminal["falseWarningRate"],
                "endpointForecastUnchanged": True,
                "prospective": False,
                "pointInTimeCohort": False,
            }
        regimes = {
            regime: {name: risk_metrics([record for record in records if record["regime"] == regime], name) for name in WARNING_NAMES}
            for regime in sorted({record["regime"] for record in records})
        }
        hypothesis_a = {
            "severeRows": len(severe),
            "recoveredRows": len(recovered),
            "recoveredShareOfSevere": len(recovered) / len(severe) if severe else None,
            "passedDiagnosticThreshold": bool(severe and len(recovered) / len(severe) >= protocol["gate"]["minimumRecoveredShareOfSevere"]),
            "endpointDownShare": float(np.average([record["endpointDown"] for record in records], weights=date_weights(records))),
            "severeDrawdownShare": risk["terminalForecast"]["prevalence"],
        }
        endpoint = endpoint_metrics(records)
        differences = [record["endpointRatioAbsoluteDifference"] for record in records]
        result[str(horizon)] = {
            "evaluationDates": evaluation_dates,
            "coverage": {"totalRows": len(original), "coveredRows": len(records), "missingRows": len(missing), "coverageRate": len(records) / len(original)},
            "hypothesisA": hypothesis_a,
            "riskWarnings": risk,
            "checks": checks,
            "historicalDiagnosticPassed": {name: all(value for key, value in check.items() if key not in ("prospective", "pointInTimeCohort")) for name, check in checks.items()},
            "passed": {name: all(check.values()) for name, check in checks.items()},
            "selected": None,
            "endpointForecast": endpoint,
            "endpointForecastUnchanged": True,
            "pathVsFrozenEndpoint": {
                "medianAbsoluteRatioDifference": float(np.median(differences)),
                "p90AbsoluteRatioDifference": float(np.quantile(differences, 0.9)),
                "overTwoPercentagePoints": float(np.mean(np.array(differences) > 0.02)),
            },
            "regimes": regimes,
            "probability": {"status": "not_applicable", "brier": None, "logLoss": None, "reason": protocol["probability"]},
            "abstentionFraction": 0.0,
            "pointInTimeCohortReady": False,
            "prospectiveEvidence": False,
        }
        saved[str(horizon)] = {"covered": records, "missing": missing}
    return result, saved


def percent(value):
    return "—" if value is None else f"{value * 100:.2f}"


def report(result):
    lines = [
        "# 기간 종료 방향과 기간 중 낙폭 분리 연구", "",
        f"등록: {result['registeredAt']} · 실행: {result['generatedAt']}", "",
        "사전 고정 가설 두 개를 검사했다. A는 종료 시점 하락과 보유기간 중 최대 낙폭이 다른 위험인지, B는 종료 가격 예측을 그대로 둔 별도 단순 경보가 심한 낙폭을 더 잘 잡는지다. 결과 후 문턱 조정이나 학습은 하지 않았다.", "",
    ]
    for horizon, study in result["horizons"].items():
        a = study["hypothesisA"]
        endpoint = study["endpointForecast"]
        lines += [
            f"## {horizon}거래일", "",
            f"경로 {study['coverage']['coveredRows']}/{study['coverage']['totalRows']} ({percent(study['coverage']['coverageRate'])}%), {len(study['evaluationDates'])}개 날짜. 심한 최대낙폭 비율 {percent(a['severeDrawdownShare'])}%, 그중 종료 하락이 아닌 회복 사례 {a['recoveredRows']}/{a['severeRows']} ({percent(a['recoveredShareOfSevere'])}%).", "",
            "| 위험경보 | 심한 낙폭 포착 % | 경보 적중 % | 잘못된 경보율 % | 경보율 % | 탐색 조건 | 승격 |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
        for name, metric in study["riskWarnings"].items():
            diagnostic = "기준" if name == "terminalForecast" else ("통과" if study["historicalDiagnosticPassed"][name] else "미통과")
            promoted = "아니오"
            lines.append(f"| {WARNING_NAMES[name]} | {percent(metric['recall'])} | {percent(metric['precision'])} | {percent(metric['falseWarningRate'])} | {percent(metric['warningRate'])} | {diagnostic} | {promoted} |")
        lines += [
            "",
            f"종료 가격 예측은 변경하지 않았다: MAPE {percent(endpoint['mape'])}%, 수익률 MAE {percent(endpoint['returnMae'])}%p, 상승/하락 포착 {percent(endpoint['upRecall'])}%/{percent(endpoint['downRecall'])}%, 균형 방향 {percent(endpoint['balancedDirectionAccuracy'])}%.", "",
        ]
    lines += [
        "## 판정", "",
        "- 이 표는 현재 구성종목과 수정 조정가격을 쓴 격리 진단이다. 시점별 구성종목 준비도 0/34 때문에 어떤 후보도 승격할 수 없고, 상장폐지·합병 누락 편향이 남는다.",
        "- 직전 63일 낙폭 경보는 포착률을 높였지만 기준보다 경보 적중률이 낮고 잘못된 경보가 늘었다. 따라서 사용자 전체 개선 조건과 가설 B를 통과한 후보는 없다.",
        "- 경로 결측은 분모에서 숨기지 않았고, 날짜별 동일 가중과 전체 행 단순 집계를 모두 저장했다. 시장 상황별·날짜별 결과와 큰 오차는 results.json 및 predictions.json.gz에 있다.",
        "- 이진 경보는 교정 확률이 아니므로 Brier/logloss는 해당 없음이다. 종료 예측과 위험경보의 역할을 분리했으며 분류기 argmax를 숫자 예측에 붙이지 않았다.",
        "- 거래비용·체결지연·회전율·포지션 규칙을 검사하지 않았으므로 매매 성과가 아니다. UI·서비스 예측·순위·운용 정책은 변경하지 않았다.",
        "- 다음 연구: 시점별 구성종목 및 상장폐지 경로가 준비된 뒤 같은 고정 규칙을 재검증하고, 그 전에는 문턱을 재튜닝하지 않는다.", "",
        "재현: `python scripts/research_drawdown_separation.py` · 입력 수집: `python scripts/collect_drawdown_paths.py` · 검증: `python scripts/test_drawdown_separation.py`", "",
        "근거: [Maximum drawdown, recovery, and momentum](https://arxiv.org/abs/2103.09906) · [Using Maximum Drawdowns to Capture Tail Risk](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3588564)", "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=FOLDER)
    args = parser.parse_args()
    folder = args.folder
    protocol_bytes = (folder / "PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    source_raw = gzip.decompress((folder / protocol["source"]).resolve().read_bytes())
    feature_raw = gzip.decompress((folder / protocol["featureSource"]).resolve().read_bytes())
    universe_bytes = (folder / protocol["universeSource"]).resolve().read_bytes()
    source, features = json.loads(source_raw), json.loads(feature_raw)
    universe = json.loads(universe_bytes)
    path_bytes, paths = read_path_snapshot(folder)
    if digest(source_raw) != protocol["sourceHashes"]["environmentRawSha256"] or digest(feature_raw) != protocol["sourceHashes"]["featureRawSha256"] or digest(universe_bytes) != protocol["sourceHashes"]["universeFileSha256"]:
        raise ValueError("Registered source hash mismatch")
    validate(protocol, source, features, paths, universe)
    horizons, predictions = evaluate(protocol, source, features, paths)
    canonical = {"version": protocol["version"], "horizons": horizons, "selection": None}
    result = {
        "version": protocol["version"], "registeredAt": protocol["registeredAt"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceMainCommit": protocol["sourceMainCommit"], "parentResearchCommit": protocol["parentResearchCommit"],
        "protocolHash": digest(protocol_bytes), "pathSnapshotHash": digest(path_bytes),
        "codeHash": digest(Path(__file__).read_bytes()),
        "canonicalResultHash": digest(json.dumps(canonical, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()),
        "historicalHoldoutRevisited": True, "pointInTimeCohortReady": False,
        "uiChanged": False, "serviceForecastChanged": False, "selection": None,
        "prospective": {"issuedForecasts": 0, "reason": "Historical path replay only; no forecast was issued before its outcome."},
        "horizons": horizons,
    }
    (folder / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    (folder / "predictions.json.gz").write_bytes(gzip.compress(json.dumps(predictions, sort_keys=True, ensure_ascii=False, allow_nan=False).encode(), mtime=0))
    (folder / "RESULTS.md").write_text(report(result))
    print("Saved", result["canonicalResultHash"], "no UI/service changes", flush=True)


if __name__ == "__main__":
    main()
