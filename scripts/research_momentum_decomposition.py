"""Evaluate pre-registered HTP/PTH momentum decomposition candidates."""
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


FOLDER = ROOT / "research/joint-indicator/momentum-decomposition-v1"
NAMES = {
    "noChange": "가격 불변",
    "priceOnly": "가격 패턴 기준",
    "simpleTrend": "단순 126일 추세",
    "total_momentum_tilt": "총 모멘텀 순위 보정",
    "htp_rank_tilt": "HTP 순위 보정",
    "pth_hype_guard": "HTP·PTH 과열 하락 경계",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def average_percentile(values: list[float]) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="stable")
    result = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        result[order[start:end]] = ((start + end - 1) / 2 + 0.5) / len(values)
        start = end
    return result


def ranked_features(rows: list[dict], features: dict) -> dict[str, dict]:
    usable = []
    for row in rows:
        key = f"{row['symbol']}|{row['origin']}"
        feature = features.get(key)
        if feature and feature["usable"]:
            usable.append((key, feature))
    if not usable:
        return {}
    result = {key: {} for key, _ in usable}
    for field in ("htp", "pth", "totalMomentum"):
        percentiles = average_percentile([float(feature[field]) for _, feature in usable])
        for (key, _), percentile in zip(usable, percentiles):
            result[key][field + "Percentile"] = float(percentile)
            result[key][field + "Score"] = float(2 * percentile - 1)
    return result


def validate(protocol: dict, environment_raw: bytes, universe_raw: bytes,
             snapshot_raw: bytes, source: dict, universe: dict, snapshot: dict) -> None:
    if digest(environment_raw) != protocol["source"]["environmentSha256"]:
        raise ValueError("Environment source changed after registration")
    if digest(universe_raw) != protocol["source"]["universeSha256"]:
        raise ValueError("Universe source changed after registration")
    if snapshot["sourceHash"] != digest(environment_raw):
        raise ValueError("Feature/source mismatch")
    if snapshot["universeHash"] != digest(universe_raw):
        raise ValueError("Feature/universe mismatch")
    if snapshot["protocolHash"] != digest((FOLDER / "PROTOCOL.json").read_bytes()):
        raise ValueError("Features were not collected under this protocol")
    for feature in snapshot["features"].values():
        if feature["usable"]:
            if not (feature["formationStart"] < feature["formationEnd"] < feature["origin"]):
                raise ValueError("Future or invalid formation window")
            if feature["through"] >= feature["origin"]:
                raise ValueError("Feature includes origin/future price")
            if abs(feature["htp"] + feature["pth"] - feature["totalMomentum"]) > 1e-12:
                raise ValueError("Momentum components do not add to total")
    members = universe["members"]
    for horizon in protocol["horizons"]:
        rows = source["stocks"][str(horizon)]["outcomes"]
        dates = sorted({row["origin"] for row in rows})
        for first, second in zip(dates, dates[1:]):
            if max(row["targetDate"] for row in rows if row["origin"] == first) >= second:
                raise ValueError("Overlapping outcome intervals")
        seen = set()
        for row in rows:
            cik = members[row["symbol"]]["cik"]
            key = (row["origin"], cik)
            if key in seen:
                raise ValueError("Duplicate CIK/origin")
            seen.add(key)


def build_rows(source_rows: list[dict], features: dict, horizon: int) -> tuple[list[dict], dict]:
    grouped: dict[str, list[dict]] = {}
    for row in source_rows:
        grouped.setdefault(row["origin"], []).append(row)
    output = []
    coverage = {
        "totalRows": len(source_rows), "usableRows": 0, "fallbackRows": 0,
        "htpAdjustedRows": 0, "hypeGuardRows": 0,
    }
    for origin in sorted(grouped):
        rows = grouped[origin]
        ranks = ranked_features(rows, features)
        for source in rows:
            key = f"{source['symbol']}|{origin}"
            feature = features.get(key)
            rank = ranks.get(key)
            price = float(source["priceOnly"])
            simple = price
            total = price
            htp = price
            guard = price
            guarded = False
            if feature and feature["usable"] and rank:
                coverage["usableRows"] += 1
                simple = float(np.exp(horizon / 126 * feature["trailing126"]))
                total = price * float(np.exp(0.025 * rank["totalMomentumScore"]))
                htp = price * float(np.exp(0.025 * rank["htpScore"]))
                guarded = rank["htpPercentile"] > 0.80 and rank["pthPercentile"] > 0.80
                if guarded:
                    guard = price * float(np.exp(-0.05))
                    coverage["hypeGuardRows"] += 1
                coverage["htpAdjustedRows"] += 1
            else:
                coverage["fallbackRows"] += 1
            values = {
                "noChange": 1.0,
                "priceOnly": price,
                "simpleTrend": simple,
                "total_momentum_tilt": total,
                "htp_rank_tilt": htp,
                "pth_hype_guard": guard,
            }
            output.append({
                "symbol": source["symbol"], "origin": origin,
                "targetDate": source["targetDate"], "y": source["y"],
                "regime": source["regime"], "inputUsable": bool(feature and feature["usable"]),
                "hypeGuarded": guarded, "rankFeature": rank,
                "methods": {
                    name: {"value": float(value), "direction": int(label(value))}
                    for name, value in values.items()
                },
            })
    return output, coverage


def date_weights(rows: list[dict]) -> np.ndarray:
    counts = {day: sum(row["origin"] == day for row in rows) for day in {r["origin"] for r in rows}}
    return np.asarray([1 / counts[row["origin"]] for row in rows], dtype=float)


def error_correlation(rows: list[dict], name: str) -> float:
    actual = np.asarray([row["y"] for row in rows], dtype=float)
    price = np.log([row["methods"]["priceOnly"]["value"] for row in rows]) - np.log(actual)
    candidate = np.log([row["methods"][name]["value"] for row in rows]) - np.log(actual)
    weights = date_weights(rows)
    price -= np.average(price, weights=weights)
    candidate -= np.average(candidate, weights=weights)
    denominator = np.sqrt(
        np.average(price * price, weights=weights)
        * np.average(candidate * candidate, weights=weights)
    )
    return float(np.average(price * candidate, weights=weights) / denominator)


def evaluate(source: dict, snapshot: dict, protocol: dict) -> tuple[dict, dict]:
    horizons = {}
    predictions = {}
    for horizon in protocol["horizons"]:
        all_rows = source["stocks"][str(horizon)]["outcomes"]
        dates = sorted({row["origin"] for row in all_rows})
        evaluation_dates = dates[len(dates) // 2:]
        selected = [row for row in all_rows if row["origin"] in evaluation_dates]
        rows, coverage = build_rows(selected, snapshot["features"], horizon)
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
            regime: {
                name: weighted_score([row for row in rows if row["regime"] == regime], name)
                for name in NAMES
            }
            for regime in sorted({row["regime"] for row in rows})
        }
        diagnostics = {
            "logErrorCorrelationWithPriceOnly": {
                name: error_correlation(rows, name)
                for name in ("total_momentum_tilt", *protocol["candidates"])
            },
            "probability": {
                "status": "not_applicable", "brier": None, "logLoss": None,
                "reason": "Numeric momentum tilts emit no class probability.",
            },
            "abstentionFraction": 0.0,
            "historicalHoldoutRevisited": True,
        }
        horizons[str(horizon)] = {
            "evaluation": metrics,
            "regimes": regimes,
            "checks": checks,
            "historicalPassed": {
                name: all(value for gate, value in check.items() if gate != "prospective")
                for name, check in checks.items()
            },
            "passed": {name: all(check.values()) for name, check in checks.items()},
            "selected": None,
            "evaluatedDates": evaluation_dates,
            "coverage": coverage,
            "diagnostics": diagnostics,
            "predictionsHash": digest(json.dumps(rows, sort_keys=True).encode()),
        }
        predictions[str(horizon)] = {
            "pairedEvaluation": [
                {
                    "symbol": row["symbol"], "origin": row["origin"],
                    "targetDate": row["targetDate"], "y": row["y"], "regime": row["regime"],
                    "inputUsable": row["inputUsable"], "hypeGuarded": row["hypeGuarded"],
                    "rankFeature": None if row["rankFeature"] is None else {
                        key: row["rankFeature"][key]
                        for key in ("htpPercentile", "pthPercentile", "totalMomentumPercentile")
                    },
                    "methods": {
                        name: row["methods"][name]
                        for name in ("priceOnly", "total_momentum_tilt", "htp_rank_tilt", "pth_hype_guard")
                    },
                }
                for row in rows
            ]
        }
    return horizons, predictions


def fmt(value) -> str:
    return "—" if value is None else f"{100 * value:.2f}"


def report(payload: dict, detailed: bool = False) -> str:
    lines = [
        "# HTP·PTH 모멘텀 분해 연구",
        "",
        f"사전 등록: {payload['registeredAt']} · 실행: {payload['generatedAt']}",
        "",
        "12–1개월 모멘텀을 과거 고점 전 상승(HTP)과 고점 후 움직임(PTH)으로 분리했다. HTP 순위의 작은 대칭 보정과 HTP·PTH가 모두 상위 20%인 종목만 낮추는 희소 경계를 결과 확인 전 고정했다.",
        "",
    ]
    for horizon, section in payload["horizons"].items():
        lines += [
            f"## {horizon}거래일",
            "",
            f"{len(section['evaluatedDates'])}개 날짜 · {section['coverage']['totalRows']}행 · 결측 대체 {section['coverage']['fallbackRows']}행 · 희소 경계 {section['coverage']['hypeGuardRows']}행",
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
                    "downPrecision", "falseDownWarningRate",
                )) + " |")
        lines.append("")
        for name in ("htp_rank_tilt", "pth_hype_guard"):
            failed = [key for key, value in section["checks"][name].items() if not value]
            correlation = section["diagnostics"]["logErrorCorrelationWithPriceOnly"][name]
            lines.append(f"- {NAMES[name]}: 미통과 {', '.join(failed)}; 가격패턴 로그오차 상관 {correlation:.3f}.")
        lines.append("")
    lines += [
        "## 판정",
        "",
        "두 후보 모두 전체 조건을 통과하지 못했으며 선택·승격하지 않는다. 동일 과거 결과를 다시 본 탐색으로 새 실전 증거가 아니다.",
        "",
        "보류율은 0%이며 결측 대체도 전체 성적에 포함했다. 숫자 보정은 확률을 출력하지 않으므로 Brier·log loss는 해당 없음이다. 거래 체결·비용·회전율을 평가하지 않아 매매 성과를 주장하지 않는다.",
        "",
        "현재 구성종목과 수정 조정가격 편향이 남고 PIT·상장폐지 생애주기 준비도는 0/34다. 논문의 횡단면 포트폴리오 수익을 재현하거나 이 장기 가격예측에 그대로 적용된다고 주장하지 않는다.",
        "",
        "UI, 서비스 예측·순위, 실전·모의운용, 자동 승격 기준은 변경하지 않았다.",
        "",
    ]
    if detailed:
        lines += [
            "## 다음 연구",
            "",
            "- HTP/PTH가 가격패턴과 높은 오차 상관을 유지하면 같은 과거 표본에서 계수·분위 문턱을 재조정하지 않는다.",
            "- 다음 우선순위는 새 발행 예측의 실제 미래 관측과 시점별 구성·상장폐지 자료 보강이다. 별도 자료가 확보될 때만 시장 상태별 HTP/PTH 역할 전환을 새 프로토콜로 검증한다.",
            "",
            "재현: `python scripts/collect_momentum_decomposition.py` 후 `PYTHONPATH=scripts python scripts/research_momentum_decomposition.py`",
            "",
            "근거: [Decomposing momentum: The forgotten component (Journal of Banking & Finance, 2024)](https://doi.org/10.1016/j.jbankfin.2024.107292)",
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
    environment_gzip = (folder / protocol["source"]["environment"]).read_bytes()
    environment_raw = gzip.decompress(environment_gzip)
    universe_raw = (folder / protocol["source"]["universe"]).read_bytes()
    snapshot_gzip = (folder / "sources/features.json.gz").read_bytes()
    snapshot_raw = gzip.decompress(snapshot_gzip)
    source = json.loads(environment_raw)
    universe = json.loads(universe_raw)
    snapshot = json.loads(snapshot_raw)
    validate(protocol, environment_raw, universe_raw, snapshot_raw, source, universe, snapshot)
    horizons, predictions = evaluate(source, snapshot, protocol)
    core = {
        "version": protocol["version"],
        "registeredAt": protocol["registeredAt"],
        "sourceMainCommit": protocol["sourceMainCommit"],
        "parentResearchCommit": protocol["parentResearchCommit"],
        "sourceHash": digest(environment_raw),
        "sourceGzipHash": digest(environment_gzip),
        "universeHash": digest(universe_raw),
        "featureSnapshotHash": digest(snapshot_gzip),
        "featureContentHash": digest(snapshot_raw),
        "protocolHash": digest(protocol_raw),
        "codeHashes": {
            "research": digest(Path(__file__).read_bytes()),
            "collector": digest(Path(__file__).with_name("collect_momentum_decomposition.py").read_bytes()),
            "metrics": digest(Path(__file__).with_name("research_relative_blends.py").read_bytes()),
            "gates": digest(Path(__file__).with_name("research_indicator_blends.py").read_bytes()),
        },
        "uiChanged": False,
        "serviceForecastChanged": False,
        "selected": None,
        "horizons": horizons,
        "prospective": {
            "issuedForecasts": 0,
            "reason": "Observed historical outcomes were used only for evaluation; no retrospective row was recorded as issued.",
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
    prediction_raw = json.dumps(
        predictions, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    (folder / "predictions.json.gz").write_bytes(gzip.compress(prediction_raw, mtime=0))
    (folder / "RESULTS.md").write_text(report(payload))
    (folder / "FINDINGS.md").write_text(report(payload, detailed=True))
    print(json.dumps({
        "canonicalHash": canonical_hash,
        "predictionsGzipHash": digest((folder / "predictions.json.gz").read_bytes()),
        "passed": {horizon: section["passed"] for horizon, section in horizons.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
