"""Pre-registered residual-momentum rank tilts; research outputs only."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from research_joint_indicator import ROOT, label
from research_indicator_blends import blend_gates
from research_relative_blends import weighted_score


FOLDER = ROOT / "research/joint-indicator/rank-tilt-v1"
NAMES = {
    "noChange": "가격 불변",
    "priceOnly": "가격 패턴 기준",
    "simpleTrend": "단순 가격 추세",
    "relative_expert": "기존 상대강도 전문가",
    "symmetric_rank_tilt": "잔차순위 대칭 보정",
    "sparse_down_tilt": "잔차순위 하락 보정",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def average_percentile(values: list[float]) -> np.ndarray:
    """Mid-rank percentile in (0,1), deterministic and invariant to row order."""
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="stable")
    result = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        # Average of zero-based ranks, shifted by half an observation.
        result[order[start:end]] = ((start + end - 1) / 2 + 0.5) / len(values)
        start = end
    return result


def rank_features(rows: list[dict], features: dict) -> dict[str, dict]:
    usable = []
    for row in rows:
        key = f"{row['symbol']}|{row['origin']}"
        feature = features.get(key)
        if feature and feature["usable"] and all(
            feature["relative"][i] is not None for i in (9, 10)
        ):
            usable.append((key, float(feature["relative"][9]), float(feature["relative"][10])))
    if not usable:
        return {}
    p126 = average_percentile([item[1] for item in usable])
    p252 = average_percentile([item[2] for item in usable])
    combined = (p126 + p252) / 2
    final = average_percentile(combined.tolist())
    return {
        key: {"percentile": float(p), "score": float(2 * p - 1)}
        for (key, _, _), p in zip(usable, final)
    }


def validate_inputs(protocol: dict, predictions_raw: bytes, features_raw: bytes,
                    relative_results_raw: bytes,
                    predictions: dict, snapshot: dict) -> None:
    expected = protocol["inputs"]
    if digest(predictions_raw) != expected["pairedPredictionsSha256"]:
        raise ValueError("Paired prediction hash changed after registration")
    if digest(features_raw) != expected["featureSnapshotSha256"]:
        raise ValueError("Feature snapshot hash changed after registration")
    if digest(relative_results_raw) != expected["relativeResultsSha256"]:
        raise ValueError("Relative research result hash changed after registration")
    for feature in snapshot["features"].values():
        for field in ("ownThrough", "marketThrough", "sectorThrough", "residualThrough"):
            if feature[field] is not None and feature[field] >= feature["origin"]:
                raise ValueError("Future feature timestamp")
    for horizon in protocol["horizons"]:
        rows = predictions[str(horizon)]["pairedEvaluation"]
        seen = set()
        for row in rows:
            key = (row["symbol"], row["origin"])
            if key in seen:
                raise ValueError("Duplicate symbol/origin")
            seen.add(key)
            if row["targetDate"] <= row["origin"]:
                raise ValueError("Invalid outcome interval")


def candidate_rows(source_rows: list[dict], features: dict) -> tuple[list[dict], dict]:
    by_origin: dict[str, list[dict]] = {}
    for row in source_rows:
        by_origin.setdefault(row["origin"], []).append(row)
    output = []
    coverage = {"totalRows": len(source_rows), "usableRows": 0,
                "symmetricAdjustedRows": 0, "sparseAdjustedRows": 0}
    for origin in sorted(by_origin):
        rows = by_origin[origin]
        ranks = rank_features(rows, features)
        for source in rows:
            row = copy.deepcopy(source)
            key = f"{row['symbol']}|{origin}"
            rank = ranks.get(key)
            price = float(row["methods"]["priceOnly"]["value"])
            symmetric = price
            sparse = price
            below_200 = False
            if rank is not None:
                coverage["usableRows"] += 1
                symmetric = price * float(np.exp(0.025 * rank["score"]))
                feature = features[key]
                below_200 = feature["absolute"][4] is not None and feature["absolute"][4] < 0
                if rank["percentile"] <= 0.20 and below_200:
                    sparse = price * float(np.exp(-0.05))
                    coverage["sparseAdjustedRows"] += 1
                coverage["symmetricAdjustedRows"] += 1
            row["rankFeature"] = None if rank is None else {
                **rank, "below200DayMean": bool(below_200)
            }
            for name, value in (("symmetric_rank_tilt", symmetric),
                                ("sparse_down_tilt", sparse)):
                row["methods"][name] = {
                    "value": float(value), "direction": int(label(value))
                }
            output.append(row)
    coverage["fallbackRows"] = coverage["totalRows"] - coverage["usableRows"]
    return output, coverage


def error_correlation(rows: list[dict], candidate: str) -> float:
    y = np.asarray([r["y"] for r in rows], dtype=float)
    a = np.log([r["methods"]["priceOnly"]["value"] for r in rows]) - np.log(y)
    b = np.log([r["methods"][candidate]["value"] for r in rows]) - np.log(y)
    # Equal date weights, matching headline evaluation.
    counts = {d: sum(r["origin"] == d for r in rows) for d in {r["origin"] for r in rows}}
    w = np.asarray([1 / counts[r["origin"]] for r in rows], dtype=float)
    a -= np.average(a, weights=w)
    b -= np.average(b, weights=w)
    denominator = np.sqrt(np.average(a * a, weights=w) * np.average(b * b, weights=w))
    return float(np.average(a * b, weights=w) / denominator)


def evaluate(predictions: dict, snapshot: dict, protocol: dict) -> tuple[dict, dict]:
    result = {}
    saved = {}
    for horizon in protocol["horizons"]:
        source_rows = predictions[str(horizon)]["pairedEvaluation"]
        rows, coverage = candidate_rows(source_rows, snapshot["features"])
        metrics = {name: weighted_score(rows, name) for name in NAMES}
        checks = {}
        for name in protocol["candidates"]:
            check = blend_gates(metrics[name], metrics["priceOnly"], metrics["noChange"], protocol)
            check.update(
                falseWarnings=(metrics[name]["falseDownWarningRate"] <=
                               metrics["priceOnly"]["falseDownWarningRate"]),
                simpleTrend=(metrics[name]["dateMeanMape"] <= metrics["simpleTrend"]["dateMeanMape"] and
                             metrics[name]["dateMeanReturnMae"] <=
                             metrics["simpleTrend"]["dateMeanReturnMae"]),
            )
            checks[name] = check
        regimes = {
            regime: {name: weighted_score([r for r in rows if r["regime"] == regime], name)
                     for name in NAMES}
            for regime in sorted({r["regime"] for r in rows})
        }
        diagnostics = {
            "logErrorCorrelationWithPriceOnly": {
                name: error_correlation(rows, name) for name in protocol["candidates"]
            },
            "probability": {
                "status": "not_applicable", "brier": None, "logLoss": None,
                "reason": "Numeric rank tilts emit no probability."
            },
            "abstentionFraction": 0.0,
            "historicalHoldoutRevisited": True,
        }
        result[str(horizon)] = {
            "evaluation": metrics,
            "regimes": regimes,
            "checks": checks,
            "historicalPassed": {
                name: all(value for gate, value in check.items() if gate != "prospective")
                for name, check in checks.items()
            },
            "passed": {name: all(check.values()) for name, check in checks.items()},
            "selected": None,
            "evaluatedDates": sorted({r["origin"] for r in rows}),
            "coverage": coverage,
            "diagnostics": diagnostics,
            "predictionsHash": digest(json.dumps(rows, sort_keys=True).encode()),
        }
        saved[str(horizon)] = {
            "pairedEvaluation": [
                {
                    "symbol": row["symbol"],
                    "origin": row["origin"],
                    "targetDate": row["targetDate"],
                    "y": row["y"],
                    "regime": row["regime"],
                    "rankFeature": row["rankFeature"],
                    "methods": {
                        name: row["methods"][name]
                        for name in ("priceOnly", "symmetric_rank_tilt", "sparse_down_tilt")
                    },
                }
                for row in rows
            ]
        }
    return result, saved


def fmt(value) -> str:
    return "—" if value is None else f"{100 * value:.2f}"


def report(payload: dict, detailed: bool = False) -> str:
    lines = [
        "# 잔차 모멘텀 횡단면 순위 보정 연구",
        "",
        f"사전 등록: {payload['registeredAt']} · 실행: {payload['generatedAt']}",
        "",
        "잔차수익률로 종목을 순위화하면 총수익률 모멘텀의 시변 시장요인 노출을 줄일 수 있다는 연구를 작은 고정 보정으로 검사했다. 결과를 본 뒤 계수나 문턱을 바꾸지 않았다.",
        "",
    ]
    for horizon, section in payload["horizons"].items():
        lines += [
            f"## {horizon}거래일",
            "",
            f"평가 {len(section['evaluatedDates'])}개 날짜, {section['coverage']['totalRows']}행 · 결측 대체 {section['coverage']['fallbackRows']}행 · 하락 보정 {section['coverage']['sparseAdjustedRows']}행",
            "",
            "| 방법 | 미래가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 균형 방향 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 경고율 % |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for name in NAMES:
            metric = section["evaluation"][name]
            lines.append("| " + NAMES[name] + " | " + " | ".join(
                fmt(metric[key]) for key in (
                    "dateMeanMape", "dateMeanReturnMae", "directionAccuracy",
                    "balancedDirectionAccuracy", "upRecall", "downRecall",
                    "downPrecision", "falseDownWarningRate"
                )) + " |")
        lines.append("")
        for name in ("symmetric_rank_tilt", "sparse_down_tilt"):
            failed = [gate for gate, passed in section["checks"][name].items() if not passed]
            corr = section["diagnostics"]["logErrorCorrelationWithPriceOnly"][name]
            lines.append(f"- {NAMES[name]}: 미통과 {', '.join(failed)}; 가격패턴 로그오차 상관 {corr:.3f}.")
        lines.append("")
    lines += [
        "## 판정",
        "",
        "두 가설 모두 전체 조건 미통과이며 승격·후보 선택은 없다. 현재 구성종목·현재 업종·수정 가격을 쓴 이미 관찰된 과거 구간이라 탐색 결과일 뿐 새 실전 증거가 아니다.",
        "",
        "보류율은 0%이고 결측은 가격패턴 기준으로 대체해 전체 표본에 포함했다. 숫자 예측이라 확률 성적은 해당 없으며 Brier/log loss를 만들지 않았다. 단기 진입·보유 및 비용·회전율·낙폭을 평가하지 않았으므로 매매 성과를 주장하지 않는다.",
        "",
        "UI, 서비스 예측·순위, 실전·모의운용, 자동 승격 정책은 변경하지 않았다.",
        "",
    ]
    if detailed:
        lines += [
            "## 다음 연구",
            "",
            "- 시점별 구성종목과 상장폐지 종목이 포함된 자료가 확보되기 전에는 같은 현재-universe 횡단면 보정을 반복 튜닝하지 않는다.",
            "- 다음 비중복 후보는 12개월 고점까지의 장기 상승(HTP)과 고점 근접도(PTH)를 분리하거나, 새 발행 예측의 실제 관측이 쌓인 뒤 사전 고정 역할 전환을 검증한다.",
            "",
            "재현: `PYTHONPATH=scripts python scripts/research_rank_tilt.py`",
            "",
            "근거: [Residual Momentum (Journal of Empirical Finance, 2011)](https://doi.org/10.1016/j.jempfin.2011.01.003) · [Erasmus 저장본](https://repub.eur.nl/pub/22252)",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=FOLDER)
    args = parser.parse_args()
    folder = args.folder
    protocol_raw = (folder / "PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_raw)
    prediction_path = (folder / protocol["inputs"]["pairedPredictions"]).resolve()
    feature_path = (folder / protocol["inputs"]["featureSnapshot"]).resolve()
    predictions_raw = prediction_path.read_bytes()
    features_raw = feature_path.read_bytes()
    relative_results_raw = (prediction_path.parent / "results.json").read_bytes()
    predictions = json.loads(gzip.decompress(predictions_raw))
    snapshot = json.loads(gzip.decompress(features_raw))
    validate_inputs(protocol, predictions_raw, features_raw, relative_results_raw,
                    predictions, snapshot)
    horizons, saved = evaluate(predictions, snapshot, protocol)
    core = {
        "version": protocol["version"],
        "registeredAt": protocol["registeredAt"],
        "sourceMainCommit": protocol["sourceMainCommit"],
        "parentResearchCommit": protocol["parentResearchCommit"],
        "protocolHash": digest(protocol_raw),
        "inputHashes": protocol["inputs"],
        "codeHash": digest(Path(__file__).read_bytes()),
        "uiChanged": False,
        "serviceForecastChanged": False,
        "selected": None,
        "horizons": horizons,
        "prospective": {
            "issuedForecasts": 0,
            "reason": "Historical paired rows were already observed; no retrospective row was recorded as issued."
        },
    }
    canonical_hash = digest(json.dumps(core, sort_keys=True, ensure_ascii=False).encode())
    payload = {
        **core,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "canonicalHash": canonical_hash,
    }
    (folder / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    prediction_bytes = json.dumps(saved, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    (folder / "predictions.json.gz").write_bytes(gzip.compress(prediction_bytes, mtime=0))
    (folder / "RESULTS.md").write_text(report(payload))
    (folder / "FINDINGS.md").write_text(report(payload, detailed=True))
    print(json.dumps({
        "canonicalHash": canonical_hash,
        "predictionsHash": digest((folder / "predictions.json.gz").read_bytes()),
        "passed": {h: q["passed"] for h, q in horizons.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
