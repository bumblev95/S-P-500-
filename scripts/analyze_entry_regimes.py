"""Research-only attribution of PR #33's frozen accounts; never fetches prices.

Regimes are lagged one SPY session. Benchmarks are diagnostic, fractional,
daily rebalanced SPY/cash sleeves with zero intermediate rebalance costs.
"""
import argparse
import csv
from datetime import datetime
import gzip
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import statistics
import struct

from render_entry_backtest import validate as validate_original

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "research/entry-backtest/2026-10-04"
DIRECTORY = BASE / "regimes"
VERSION = "entry-context-v1-regime-attribution-v1"
FIXED_DATA_SHA256 = "0307d3266187abea5e008fbaefd71a447d78298365ff41d2f7939516a12cf92a"
PRICE_FIELDS = ["date", "t", "end", "open", "high", "low", "close", "volume", "signalPrice"]
SERIES = ["strategy", "spy", "spyCashFullMean", "spyCashGroupMean", "spyCashLagged"]
# No sample quantiles or return-dependent thresholds.
DEFINITIONS = {
    "asOf": "previous SPY session close, including the first evaluation day",
    "sma200": {"window": 200, "above": "known close >= known SMA200"},
    "trend63": {"lookback": 63, "up": "known close / close 63 sessions earlier - 1 > 0"},
    "volatility63": {"returns": "log close-to-close", "window": 63, "ddof": 1,
                     "annualization": 252, "lowUpperExclusive": 0.15, "highLowerInclusive": 0.25},
    "cashRate": 0, "rebalanceCost": 0, "fractionalShares": True,
    "capture": "ratio of geometric mean DAILY returns on positive/negative raw SPY price days",
    "drawdown": "both chronologically stitched selected days and separate contiguous episodes",
    "fixedMeanWeight": "ex-post control, not a point-in-time trading signal",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def csv_text(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def close(a, b, message="numeric reconciliation", tolerance=1e-9):
    if not math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance):
        raise ValueError(f"{message}: {a} != {b}")


def prepare_spy(input_path, directory, original, sources):
    raw = gzip.decompress(input_path.read_bytes())
    digest = sha(raw)
    if digest != FIXED_DATA_SHA256 or digest != original["input"]["sha256"]:
        raise ValueError("Price input differs from PR #33's fixed dataset; do not re-download/substitute")
    data = json.loads(raw)
    rows = [{k: row[k] for k in PRICE_FIELDS} for row in data["stocks"]["SPY"]["rows"]]
    encoded = csv_text(rows, PRICE_FIELDS).encode()
    source = sources["sources"]["SPY"]
    manifest = {
        "version": VERSION, "originalPRHead": "e439161af57a418727ba14e03d73808821ceefe8",
        "datasetSHA256": digest, "spyProviderSHA256": source["sha256"],
        "spyInputSHA256": sha(encoded), "rows": len(rows),
        "first": rows[0]["date"], "last": rows[-1]["date"],
        "basis": data["basis"], "columns": PRICE_FIELDS,
        "extraction": "SPY rows directly from hash-verified fixed prices.json.gz; no new requests",
    }
    directory.mkdir(parents=True, exist_ok=True)
    for filename, content in (("spy-input.csv", encoded),
                              ("input-manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())):
        p = directory / filename
        if p.exists() and p.read_bytes() != content:
            raise ValueError("Refusing to replace a different fixed input: " + str(p))
        if not p.exists():
            p.write_bytes(content)


def load_spy(directory, original, sources):
    manifest = json.loads((directory / "input-manifest.json").read_text())
    encoded = (directory / "spy-input.csv").read_bytes()
    if manifest["datasetSHA256"] != FIXED_DATA_SHA256 or manifest["datasetSHA256"] != original["input"]["sha256"]:
        raise ValueError("Fixed dataset identity mismatch")
    if manifest["spyInputSHA256"] != sha(encoded):
        raise ValueError("Fixed SPY input hash mismatch")
    if manifest["spyProviderSHA256"] != sources["sources"]["SPY"]["sha256"]:
        raise ValueError("Original SPY provider hash mismatch")
    rows = []
    for row in read_csv(directory / "spy-input.csv"):
        converted = {k: row[k] if k == "date" else int(row[k]) if k in ("t", "end", "volume")
                     else float(row[k]) for k in PRICE_FIELDS}
        if not all(math.isfinite(converted[k]) for k in PRICE_FIELDS if k != "date"):
            raise ValueError("Non-finite SPY input")
        if not (0 < converted["low"] <= min(converted["open"], converted["close"])
                <= max(converted["open"], converted["close"]) <= converted["high"]):
            raise ValueError("Invalid fixed SPY OHLC")
        if converted["t"] >= converted["end"] or (rows and converted["date"] <= rows[-1]["date"]):
            raise ValueError("Unordered SPY input")
        rows.append(converted)
    source = sources["sources"]["SPY"]
    if (len(rows), rows[0]["date"], rows[-1]["date"]) != (manifest["rows"], manifest["first"], manifest["last"]):
        raise ValueError("Fixed SPY manifest mismatch")
    if (len(rows), rows[0]["date"], rows[-1]["date"]) != (source["rows"], source["first"], source["last"]):
        raise ValueError("Fixed SPY source coverage mismatch")
    return rows, manifest


def volatility_state(value):
    return "low" if value < 0.15 else "medium" if value < 0.25 else "high"


def regime_features(spy, i):
    """Features for return date i, based strictly on rows ending at i-1."""
    j = i - 1
    if j < 199:
        return None
    known = spy[j]
    sma = statistics.fmean(r["close"] for r in spy[j - 199:j + 1])
    trend = known["close"] / spy[j - 63]["close"] - 1
    log_returns = [math.log(spy[k]["close"] / spy[k - 1]["close"]) for k in range(j - 62, j + 1)]
    volatility = statistics.stdev(log_returns) * math.sqrt(252)
    ma_state, trend_state = ("above" if known["close"] >= sma else "below"), ("up" if trend > 0 else "downFlat")
    vol_state = volatility_state(volatility)
    return {"asOf": known["date"], "closeKnown": known["close"], "sma200Known": sma,
            "trend63Known": trend, "volatility63Known": volatility,
            "sma200": ma_state, "trend63": trend_state, "volatility63": vol_state,
            "sma200Trend63": ma_state + "|" + trend_state,
            "joint": ma_state + "|" + trend_state + "|" + vol_state}


def benchmark_return(price_return, weight, first, last, cfg):
    """Self-financing SPY/cash sleeve, reset to weight BEFORE the day's return.

    Initial cash allocated to SPY pays entry costs; final grown sleeve pays exit
    costs. At intermediate boundaries the rebalance is frictionless by design.
    """
    if not math.isfinite(weight) or not 0 <= weight <= 1:
        raise ValueError("SPY sleeve weight must be between 0 and 1")
    buy_factor = (1 + cfg["slip"]) * (1 + cfg["fee"]) if first else 1
    sell_factor = (1 - cfg["slip"]) * (1 - cfg["fee"]) if last else 1
    return (1 - weight) + weight / buy_factor * (1 + price_return) * sell_factor - 1


def account_days(spy, curve, portfolio, cfg, start, end):
    before = [r for r in curve if r["phase"]]
    rows = [r for r in curve if not r["phase"]]
    if len(before) != 1 or before[0]["phase"] != "beforeFirstOpen" or before[0]["date"] != start:
        raise ValueError("Expected the original account's before-first-open row")
    close(float(before[0]["equity"]), portfolio["initial"], "Initial capital")
    if float(before[0]["exposure"]) != 0:
        raise ValueError("Original initial account must be cash")
    reference = [(i, r) for i, r in enumerate(spy) if start <= r["date"] <= end]
    if [r["date"] for r in rows] != [r["date"] for _, r in reference]:
        raise ValueError("Account/SPY trading dates differ")
    output, previous_equity, previous_weight = [], portfolio["initial"], 0.0
    sell_loss = 1 - (1 - cfg["slip"]) * (1 - cfg["fee"])
    full_mean = statistics.fmean(float(r["exposure"]) / float(r["equity"]) for r in rows)
    close(full_mean, portfolio["meanExposure"], "Original mean exposure")
    for k, ((i, bar), row) in enumerate(zip(reference, rows)):
        features = regime_features(spy, i)
        if features is None:
            raise ValueError("Insufficient regime warm-up; do not silently drop account days")
        equity, cash, exposure = (float(row[f]) for f in ("equity", "cash", "exposure"))
        if not all(math.isfinite(v) for v in (equity, cash, exposure)) or equity <= 0 or min(cash, exposure) < 0:
            raise ValueError("Invalid original account curve")
        close(equity, cash + exposure, "Curve accounting")
        if int(row["at"]) != bar["end"]:
            raise ValueError("Account/SPY close clock differs")
        first, last = k == 0, k == len(rows) - 1
        liquid_equity = equity - exposure * sell_loss if last else equity
        strategy_return = liquid_equity / previous_equity - 1
        price_return = bar["close"] / (bar["open"] if first else spy[i - 1]["close"]) - 1
        output.append({"index": k, "date": bar["date"], "year": bar["date"][:4], **features,
                       "first": first, "last": last, "exposure": exposure / equity,
                       "laggedExposure": previous_weight, "spyPriceReturn": price_return,
                       "strategyReturn": strategy_return,
                       "spyNetReturn": benchmark_return(price_return, 1, first, last, cfg),
                       "spyCashFullMeanReturn": benchmark_return(price_return, full_mean, first, last, cfg),
                       "spyCashLaggedReturn": benchmark_return(price_return, previous_weight, first, last, cfg)})
        previous_equity, previous_weight = equity, exposure / equity
    close(previous_equity, portfolio["markEquity"], "Original mark equity")
    close(liquid_equity, portfolio["liquidationEquivalentEquity"], "Terminal liquidation equity")
    return output


def compound(returns):
    return math.expm1(math.fsum(math.log1p(r) for r in returns))


def drawdown(returns):
    wealth = peak = 1.0
    maximum = 0.0
    for r in returns:
        wealth *= 1 + r
        peak = max(peak, wealth)
        maximum = max(maximum, 1 - wealth / peak)
    return maximum


def episodes(indices):
    groups = []
    for i in indices:
        if not groups or i != groups[-1][-1] + 1:
            groups.append([])
        groups[-1].append(i)
    return groups


def capture(returns, reference, price_returns, positive):
    indices = [i for i, r in enumerate(price_returns) if (r > 0 if positive else r < 0)]
    if not indices:
        return None
    a = math.expm1(statistics.fmean(math.log1p(returns[i]) for i in indices))
    b = math.expm1(statistics.fmean(math.log1p(reference[i]) for i in indices))
    return None if abs(b) < 1e-15 else a / b * 100


def series_metrics(returns, reference, price_returns, episode_local):
    if not returns:
        return {k: None for k in ("return", "annualizedActiveReturn", "maxDrawdownStitched",
                                  "maxDrawdownContinuousEpisode", "upCapture", "downCapture")}
    return {"return": compound(returns),
            "annualizedActiveReturn": math.expm1(252 * statistics.fmean(math.log1p(r) for r in returns)),
            "maxDrawdownStitched": drawdown(returns),
            "maxDrawdownContinuousEpisode": max(drawdown(returns[i] for i in group) for group in episode_local),
            "upCapture": capture(returns, reference, price_returns, True),
            "downCapture": capture(returns, reference, price_returns, False)}


def summarize(days, indices, cfg):
    selected = [days[i] for i in indices]
    spans = episodes(indices)
    local_index = {i: k for k, i in enumerate(indices)}
    local_spans = [[local_index[i] for i in group] for group in spans]
    n = len(selected)
    weight = statistics.fmean(d["exposure"] for d in selected) if n else None
    values = {
        "strategy": [d["strategyReturn"] for d in selected],
        "spy": [d["spyNetReturn"] for d in selected],
        "spyCashFullMean": [d["spyCashFullMeanReturn"] for d in selected],
        "spyCashGroupMean": [benchmark_return(d["spyPriceReturn"], weight, d["first"], d["last"], cfg) for d in selected],
        "spyCashLagged": [d["spyCashLaggedReturn"] for d in selected],
    }
    price = [d["spyPriceReturn"] for d in selected]
    metrics = {name: series_metrics(returns, values["spy"], price, local_spans) for name, returns in values.items()}
    logs = {name: math.fsum(math.log1p(r) for r in returns) for name, returns in values.items()}
    attribution = None if not n else {
        "cashLevelLogPP": 100 * (logs["spyCashGroupMean"] - logs["spy"]),
        "exposureTimingLogPP": 100 * (logs["spyCashLagged"] - logs["spyCashGroupMean"]),
        "residualLogPP": 100 * (logs["strategy"] - logs["spyCashLagged"]),
        "totalExcessLogPP": 100 * (logs["strategy"] - logs["spy"]),
    }
    if attribution:
        close(sum(attribution[k] for k in ("cashLevelLogPP", "exposureTimingLogPP", "residualLogPP")),
              attribution["totalExcessLogPP"], "Log attribution identity")
    excess = {name: None if not n else metrics["strategy"]["return"] - metrics[name]["return"]
              for name in SERIES if name != "strategy"}
    return {"sessions": n, "episodes": len(spans), "longestEpisode": max(map(len, spans), default=0),
            "first": selected[0]["date"] if n else None, "last": selected[-1]["date"] if n else None,
            "upDays": sum(r > 0 for r in price), "downDays": sum(r < 0 for r in price), "flatDays": sum(r == 0 for r in price),
            "meanExposure": weight, "meanLaggedExposure": statistics.fmean(d["laggedExposure"] for d in selected) if n else None,
            "series": metrics, "excessReturn": excess, "attribution": attribution}


def all_groups(days):
    axes = {
        "sma200": ["above", "below"], "trend63": ["up", "downFlat"],
        "volatility63": ["low", "medium", "high"],
        "sma200Trend63": ["|".join(v) for v in itertools.product(["above", "below"], ["up", "downFlat"])],
        "joint": ["|".join(v) for v in itertools.product(["above", "below"], ["up", "downFlat"], ["low", "medium", "high"])],
        "year": sorted({d["year"] for d in days}),
    }
    groups = [("overall", "all", list(range(len(days))))]
    for axis, labels in axes.items():
        partition = []
        for label in labels:
            indices = [i for i, d in enumerate(days) if d[axis] == label]
            partition.extend(indices)
            groups.append((axis, label, indices))
        if sorted(partition) != list(range(len(days))):
            raise ValueError("Regime partition lost/duplicated sessions: " + axis)
    return groups


def analyze(spy, original, curves):
    result, daily = {}, []
    reference = [r for r in spy if original["start"] <= r["date"] <= original["end"]]
    years = (reference[-1]["end"] - reference[0]["t"]) / (365.25 * 86400000)
    for scenario in ("stable", "watch"):
        portfolio = original["scenarios"][scenario]["portfolio"]
        days = account_days(spy, curves[scenario], portfolio, original["costRisk"], original["start"], original["end"])
        if len(days) != original["scenarios"][scenario]["frequency"]["sessions"]:
            raise ValueError("Original session count mismatch")
        summaries = [{"axis": axis, "regime": label, **summarize(days, indices, original["costRisk"])}
                     for axis, label, indices in all_groups(days)]
        overall = summaries[0]
        for metric in overall["series"].values():
            metric["cagr"] = math.expm1(math.log1p(metric["return"]) / years)
        close(overall["series"]["strategy"]["return"], portfolio["liquidationEquivalentReturn"], "Original net return")
        close(overall["series"]["strategy"]["cagr"], portfolio["cagr"], "Original CAGR")
        close(overall["series"]["strategy"]["maxDrawdownStitched"], portfolio["maxDrawdown"], "Original drawdown")
        close(overall["series"]["spy"]["return"], portfolio["benchmark"]["netReturn"], "Original SPY net return")
        close(overall["series"]["spy"]["cagr"], portfolio["benchmark"]["cagr"], "Original SPY CAGR")
        close(overall["series"]["spy"]["maxDrawdownStitched"], portfolio["benchmark"]["maxDrawdown"], "Original SPY drawdown")
        # Non-terminal years must reproduce the original marked annual returns.
        for summary in summaries:
            if summary["axis"] == "year" and summary["regime"] != original["end"][:4]:
                prior = portfolio["annual"][summary["regime"]]
                close(summary["series"]["strategy"]["return"], prior["return"], "Original annual account")
                close(summary["series"]["spy"]["return"], prior["benchmarkReturn"], "Original annual SPY")
        # Every disjoint axis must reassemble the full log returns of unchanged series.
        for axis in ("sma200", "trend63", "volatility63", "sma200Trend63", "joint", "year"):
            partition = [q for q in summaries if q["axis"] == axis]
            for name in ("strategy", "spy", "spyCashFullMean", "spyCashLagged"):
                reassembled = math.fsum(math.log1p(q["series"][name]["return"]) for q in partition if q["sessions"])
                close(reassembled, math.log1p(overall["series"][name]["return"]), "Partition return identity")
        result[scenario] = {"fullMeanWeight": portfolio["meanExposure"], "calendarYears": years, "summaries": summaries}
        daily.extend({"scenario": scenario, **d} for d in days)
    return result, daily


def output_csvs(result, daily):
    fields = ["scenario", "index", "date", "year", "asOf", "closeKnown", "sma200Known", "trend63Known", "volatility63Known",
              "sma200", "trend63", "volatility63", "sma200Trend63", "joint", "first", "last", "exposure", "laggedExposure",
              "spyPriceReturn", "strategyReturn", "spyNetReturn", "spyCashFullMeanReturn", "spyCashLaggedReturn"]
    metrics = []
    for scenario, account in result.items():
        for q in account["summaries"]:
            row = {"scenario": scenario, **{k: q[k] for k in ("axis", "regime", "sessions", "episodes", "longestEpisode",
                   "first", "last", "upDays", "downDays", "flatDays", "meanExposure", "meanLaggedExposure")}}
            for name, values in q["series"].items():
                for k in ("return", "annualizedActiveReturn", "maxDrawdownStitched", "maxDrawdownContinuousEpisode", "upCapture", "downCapture"):
                    row[name + "_" + k] = values[k]
                row[name + "_cagr"] = values.get("cagr")
            for name, value in q["excessReturn"].items():
                row["excess_" + name] = value
            for k in ("cashLevelLogPP", "exposureTimingLogPP", "residualLogPP", "totalExcessLogPP"):
                row[k] = (q["attribution"] or {}).get(k)
            metrics.append(row)
    return {"daily.csv": csv_text(daily, fields), "metrics.csv": csv_text(metrics, list(metrics[0]))}


def pct(value, signed=False):
    return "—" if value is None else f"{value * 100:+.2f}%" if signed else f"{value * 100:.2f}%"


def capture_text(value):
    return "—" if value is None else f"{value:.1f}%"


def label_text(value):
    # Keep report labels Korean; chart labels are English for portable fonts.
    korean = {"above": "200일선 위", "below": "200일선 아래", "up": "63일 상승", "downFlat": "63일 하락·보합",
              "low": "변동성 <15%", "medium": "변동성 15–25%", "high": "변동성 ≥25%"}
    return " · ".join(korean.get(v, v) for v in value.split("|"))


def get_summary(result, scenario, axis, regime):
    return next(q for q in result[scenario]["summaries"] if q["axis"] == axis and q["regime"] == regime)


def report_text(result):
    a, b = (get_summary(result, s, "overall", "all") for s in ("stable", "watch"))
    lines = ["# 현행 계좌의 레짐·노출 분석 — 2026-10-04", "",
        "PR #33의 **동일한 고정 가격·규칙·stable/watch 계좌**를 분해했다. 평가 기간은 "
        "2017-10-02–2026-10-02, 2,263거래일이다. 레짐별 결과를 본 뒤 생산 판정이나 임계값을 바꾸지 않았다.", ""]
    if all(q["excessReturn"]["spyCashGroupMean"] < 0 for q in (a, b)):
        lines += ["**전체 성과 부진은 단순 현금 비중으로 설명되지 않는다.** 평균 투자 노출을 맞춘 "
                  "SPY+현금도 두 계좌를 크게 앞섰다. 하락장 방어 여부는 아래의 하락 추세·연도별 "
                  "결과와 노출 추종 benchmark를 함께 확인해야 한다.", ""]
    yr = [get_summary(result, s, "year", "2022") for s in ("stable", "watch")]
    lines += [f"**2022년 방어는 현금 수준만의 효과가 아니었다.** 전략은 "
              f"{pct(yr[0]['series']['strategy']['return'])} / {pct(yr[1]['series']['strategy']['return'])}, "
              f"그해 평균 노출을 맞춘 SPY+현금은 {pct(yr[0]['series']['spyCashGroupMean']['return'])} / "
              f"{pct(yr[1]['series']['spyCashGroupMean']['return'])}였다(stable / watch 순). "
              "그러나 다른 하락 추세 구간과 재상승 참여까지 고려하면 일반적인 방어 필터의 우위가 "
              "확인됐다고 결론낼 수는 없다.", "",
              f"전 기간 일별 상승/하락 포착률은 stable "
              f"{capture_text(a['series']['strategy']['upCapture'])} / {capture_text(a['series']['strategy']['downCapture'])}, "
              f"watch {capture_text(b['series']['strategy']['upCapture'])} / {capture_text(b['series']['strategy']['downCapture'])}다. "
              "두 계좌 모두 상승일 참여보다 하락일 참여가 컸다. 이 비율은 사후 날짜 집합의 일별 진단이다.", ""]
    lines += ["## 전 기간: 현금 수준과 노출 시점", "",
              "| 가정 | 경로 | CAGR | 누적 수익률 | 종가 최대낙폭 | SPY 목표 비중 |",
              "| --- | --- | ---: | ---: | ---: | ---: |"]
    for s in ("stable", "watch"):
        q = get_summary(result, s, "overall", "all")
        for name, title, weight in (("strategy", "원 전략", q["meanExposure"]),
                                    ("spy", "SPY 가격 보유", 1),
                                    ("spyCashFullMean", "평균 노출 고정 SPY+현금", q["meanExposure"]),
                                    ("spyCashLagged", "전날 노출 추종 SPY+현금", q["meanLaggedExposure"])):
            m = q["series"][name]
            lines.append(f"| {s} | {title} | {pct(m['cagr'])} | {pct(m['return'])} | {pct(m['maxDrawdownStitched'])} | {pct(weight)} |")
    lines += ["", "원 전략의 비중은 평균 **종가** 노출, 노출 추종의 비중은 평균 **직전 종가** 목표다. "
              "현금 이자는 0이며 SPY 배당을 제외한다. 누적 수익률·CAGR은 원 연구와 같은 마지막 가상 청산 비용까지 포함한다.", "",
              "SPY+현금은 분수 주식으로 매일 비중을 맞추는 **사후 통제용 합성 benchmark**다. "
              "중간 리밸런싱 비용은 0, 최초·최종 sleeve 거래에만 원 연구의 비용을 적용한다. "
              "평균 비중을 실제 과거 매매에 사용할 수 있었다고 주장하지 않는다. 전날 노출 추종도 "
              "장중 손절/진입을 복원하지 않는다.", "",
              "## 과거 정보만 사용하는 레짐", "",
              "수익 발생일의 **직전 SPY 거래일 종가까지** SMA200, 63거래일 가격 추세, "
              "63개 로그수익률의 표본 표준편차×√252를 계산한다. 변동성 경계는 15%·25%로 고정했고 "
              "전체 표본 분위수나 결과 최적화를 사용하지 않았다. SMA200과 같은 종가는 위, "
              "63일 추세가 0이면 하락·보합으로 분류한다.", "",
              "### 200일선 × 63일 추세", "",
              "아래의 수익률은 **해당 날짜들만 시간순으로 이어 붙인 복리 수익률**이다. "
              "독립 계좌나 연속 보유 수익률이 아니다. 구간 평균 비중 benchmark는 해당 날짜의 "
              "평균 종가 노출을 맞춘다. 구간 밖 손익을 포함하거나 경계에서 새로 매매하지 않는다.", "",
              "| 레짐 | 가정 | 거래일 | 평균 노출 | 전략 | SPY | 구간 평균 SPY+현금 | 전날 노출 SPY+현금 | 전략−평균비중 |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for regime in ["above|up", "above|downFlat", "below|up", "below|downFlat"]:
        for s in ("stable", "watch"):
            q = get_summary(result, s, "sma200Trend63", regime)
            m = q["series"]
            lines.append(f"| {label_text(regime)} | {s} | {q['sessions']} | {pct(q['meanExposure'])} | "
                         f"{pct(m['strategy']['return'])} | {pct(m['spy']['return'])} | {pct(m['spyCashGroupMean']['return'])} | "
                         f"{pct(m['spyCashLagged']['return'])} | {pct(q['excessReturn']['spyCashGroupMean'], True)}p |")
    bear = get_summary(result, "stable", "sma200Trend63", "below|downFlat")
    lines += ["", f"‘200일선 아래·63일 하락’의 {bear['sessions']}거래일에도 SPY의 날짜 연결 수익률은 "
              f"{pct(bear['series']['spy']['return'])}였다. **과거 추세가 하락이라는 레짐은 다음 날도 "
              "하락한다는 뜻이 아니다.** 후행 필터가 여전히 하락 상태인 급반등 날짜가 포함된다. "
              "이 구간에서 작은 일별 하락 포착률만 보고 방어 성과를 좋다고 평가하면 "
              "놓친 회복 수익을 빠뜨리게 된다.", "", "### 낙폭과 상승·하락 포착", "",
              "| 레짐 | 가정 | episode 수 | 전략 합성 낙폭 | 전략 연속 episode 낙폭 | SPY 합성 낙폭 | 상승일 / 하락일 | 전략 상승 포착 | 전략 하락 포착 |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for regime in ["above|up", "above|downFlat", "below|up", "below|downFlat"]:
        for s in ("stable", "watch"):
            q = get_summary(result, s, "sma200Trend63", regime)
            m = q["series"]["strategy"]
            lines.append(f"| {label_text(regime)} | {s} | {q['episodes']} | {pct(m['maxDrawdownStitched'])} | "
                         f"{pct(m['maxDrawdownContinuousEpisode'])} | {pct(q['series']['spy']['maxDrawdownStitched'])} | "
                         f"{q['upDays']} / {q['downDays']} | {capture_text(m['upCapture'])} | {capture_text(m['downCapture'])} |")
    lines += ["", "포착률은 비용 전 SPY가 오른/내린 **일별** 날짜 집합에서 비용 포함 일수익률의 "
              "기하평균 비율이다. 월별 포착률과 다르다. 하락 포착률이 작으면 손실 참여가 작고, "
              "음수이면 해당 하락일 집합의 전략 기하평균 수익률이 양수다. 시장이 하락 추세여도 "
              "그 안의 상승일에는 별도로 상승 포착률을 계산한다.", "",
              "### 실현 변동성", "",
              "| 레짐 | 가정 | 거래일 | 평균 노출 | 전략 | SPY | 구간 평균 SPY+현금 | 전략−평균비중 | 전략 합성 낙폭 | 상승 포착 | 하락 포착 |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for regime in ("low", "medium", "high"):
        for s in ("stable", "watch"):
            q = get_summary(result, s, "volatility63", regime)
            m = q["series"]["strategy"]
            lines.append(f"| {label_text(regime)} | {s} | {q['sessions']} | {pct(q['meanExposure'])} | {pct(m['return'])} | "
                         f"{pct(q['series']['spy']['return'])} | {pct(q['series']['spyCashGroupMean']['return'])} | "
                         f"{pct(q['excessReturn']['spyCashGroupMean'], True)}p | {pct(m['maxDrawdownStitched'])} | "
                         f"{capture_text(m['upCapture'])} | {capture_text(m['downCapture'])} |")
    lines += ["", "개별 SMA200·63일 추세 축과 세 축의 **12구간**은 `metrics.csv`와 `results.json`에 "
              "전부 기록했다. 0거래일 구간은 null이며 적은 거래일/episode 구간을 확증으로 해석하지 않는다.", "",
              "## 연별 노출 일치 비교", "",
              "| 연도 | 가정 | 평균 노출 | 전략 | SPY | 연도 평균 SPY+현금 | 전날 노출 SPY+현금 | 전략−평균비중 | 전략−전날노출 |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for year in [q["regime"] for q in result["stable"]["summaries"] if q["axis"] == "year"]:
        for s in ("stable", "watch"):
            q = get_summary(result, s, "year", year)
            m = q["series"]
            lines.append(f"| {year} | {s} | {pct(q['meanExposure'])} | {pct(m['strategy']['return'])} | {pct(m['spy']['return'])} | "
                         f"{pct(m['spyCashGroupMean']['return'])} | {pct(m['spyCashLagged']['return'])} | "
                         f"{pct(q['excessReturn']['spyCashGroupMean'], True)}p | {pct(q['excessReturn']['spyCashLagged'], True)}p |")
    lines += ["", "2017년·2026년은 부분 연도다. 2026년만 마지막 가상 청산 비용을 포함하므로 기존 "
              "연별 종가 평가 표보다 조금 낮다. 다른 연도는 원 연구 수익률과 일치한다.", "",
              "## 효과 분리의 범위", "",
              "구간 평균 비중 SPY+현금과 SPY의 차이는 현금 **수준** 진단, 전날 노출 추종과 "
              "구간 평균 비중의 차이는 노출 **시점** 진단이다. 전략과 노출 추종의 차이에는 "
              "종목 선택·업종/beta·진입·손절·청산·실제 비용·장중 노출 차이가 함께 남는다. "
              "이를 종목 선택만의 alpha 또는 각각의 인과 효과로 부르지 않는다.", "",
              "`results.json`에는 이 세 단계의 **로그수익 차이(%p)**가 정확히 합산되어 전략−SPY와 "
              "일치하는 귀속도 남겼다. 원 수익률 차이(%p)와 로그수익 차이(%p)를 섞지 않는다.", "",
              "전체 평균비중 비교와 2022년 한 해의 방어는 별개다. 방어 용도에는 다른 하락 episode, "
              "재상승 시 참여·회복, 실제 필터 전환의 비용을 별도의 고정 연구에서 확인해야 한다. "
              "이번에는 레짐을 사용해 매수나 보유를 바꾸는 전략을 만들거나 우승 구간을 최적화하지 않았다.", "",
              "## 재현·검증", "",
              "```bash", "python scripts/analyze_entry_regimes.py", "python -m unittest discover -s scripts -p test_entry_regimes.py",
              "python scripts/analyze_entry_regimes.py --validate-only", "```", "",
              "고정 SPY 추출본·기존 계좌 곡선이 저장소에 있으므로 **재다운로드 없이** 재현한다. "
              "원 가격 번들에서 추출 출처를 다시 검증하려면:", "", "```bash",
              "python scripts/analyze_entry_regimes.py --input research/history/entry-backtest-2026-10-04/prices.json.gz", "```", "",
              "출력은 이 research 폴더에만 쓴다. 입력·기존 결과/규칙/곡선·분석 코드·프로토콜 해시, "
              "2×2,263개의 일별 수익/레짐/전날 노출, 모든 benchmark의 구간 성과를 보존했다. "
              "미래/당일 가격 변경 불변성, 정확한 lookback, 경계·빈 구간, 비용·포착률, 낙폭 episode, "
              "현금/노출 분해·복리 합산 및 원 CAGR·연별 수익/최대낙폭 일치를 검증한다.", "",
              "![노출 일치 비교와 레짐 초과수익](regime-analysis.png)", "",
              "정의는 [PROTOCOL.md](PROTOCOL.md), 전체 지표는 [metrics.csv](metrics.csv), "
              "일별 원장은 [daily.csv](daily.csv)다. 이 요청 후에 정의된 사후 연구이고 생존 편향, "
              "현재 업종·수정/분할 조정 가격, 배당 제외, 당시 실제 신용 상태 미복원이라는 원 연구의 "
              "제약을 그대로 승계한다. 매수 TOP·production threshold·forward 계좌는 변경하지 않았다.", ""]
    return "\n".join(lines)


def render_chart(directory, result, daily):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 8.7), sharey="row", gridspec_kw={"height_ratios": [1.25, 1]})
    colors = {"strategyReturn": "#d17b28", "spyNetReturn": "#454e5d", "spyCashFullMeanReturn": "#3877b3", "spyCashLaggedReturn": "#339184"}
    names = {"strategyReturn": "Original strategy", "spyNetReturn": "SPY price", "spyCashFullMeanReturn": "SPY + cash, mean exposure",
             "spyCashLaggedReturn": "SPY + cash, previous-day exposure"}
    for col, scenario in enumerate(("stable", "watch")):
        rows = [d for d in daily if d["scenario"] == scenario]
        dates = [datetime.fromisoformat(d["date"]) for d in rows]
        for key, color in colors.items():
            curve = np.cumprod([1 + d[key] for d in rows])
            axes[0, col].plot(dates, curve, lw=1.35, color=color, label=names[key])
        axes[0, col].set_title(f"{scenario}: same frozen account, exposure controls", loc="left", fontsize=11)
        axes[0, col].set_ylabel("Net wealth / initial capital")
        axes[0, col].legend(frameon=False, fontsize=8, loc="upper left")
        axes[0, col].set_xlim(dates[0], dates[-1])
        regimes = ["above|up", "above|downFlat", "below|up", "below|downFlat"]
        x = np.arange(len(regimes))
        for offset, key, color, name in ((-.18, "spyCashGroupMean", "#3877b3", "Strategy - regime mean SPY/cash"),
                                         (.18, "spyCashLagged", "#339184", "Strategy - lagged exposure SPY/cash")):
            y = [100 * get_summary(result, scenario, "sma200Trend63", r)["excessReturn"][key] for r in regimes]
            bars = axes[1, col].bar(x + offset, y, width=.33, color=color, label=name)
            axes[1, col].bar_label(bars, fmt="%.1f", fontsize=8, padding=3)
        counts = [get_summary(result, scenario, "sma200Trend63", r)["sessions"] for r in regimes]
        axes[1, col].set_xticks(x, [f"Above / up\n(n={counts[0]})", f"Above / down\n(n={counts[1]})",
                                  f"Below / up\n(n={counts[2]})", f"Below / down\n(n={counts[3]})"], fontsize=9)
        axes[1, col].axhline(0, color="#68717f", linewidth=.7)
        axes[1, col].set_ylabel("Stitched return difference (pp)")
        axes[1, col].margins(y=.22)
    handles, labels = axes[1, 0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=9, loc="lower center", bbox_to_anchor=(.52, .092), ncol=2)
    for ax in axes.flat:
        ax.grid(axis="y", color="#dce1e7", linewidth=.6)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("PR #33 regime attribution: previous-session SPY information", x=.065, ha="left", fontsize=14)
    fig.text(.065, .025, "2017-10-02 to 2026-10-02. Net endpoint costs; no dividends/cash interest; zero benchmark rebalance costs.\n"
             "Regime returns concatenate non-contiguous days. Ex-post exposure controls; exploratory, current-universe survivorship bias.",
             fontsize=9, color="#4d5767")
    fig.subplots_adjust(left=.07, right=.985, top=.915, bottom=.19, hspace=.35, wspace=.24)
    fig.savefig(directory / "regime-analysis.png", dpi=170)
    plt.close(fig)


def compare_nested(actual, expected, trail="results"):
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise ValueError("Saved result fields differ: " + trail)
        for k, v in expected.items():
            compare_nested(actual[k], v, trail + "." + str(k))
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError("Saved result count differs: " + trail)
        for i, v in enumerate(expected):
            compare_nested(actual[i], v, trail + f"[{i}]")
    elif isinstance(expected, float):
        close(actual, expected, trail, 1e-11)
    elif actual != expected:
        raise ValueError("Saved result differs: " + trail)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Optional original fixed prices.json.gz, to verify/extract SPY")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--no-chart", action="store_true")
    args = parser.parse_args()
    original = json.loads((BASE / "results.json").read_text())
    sources = json.loads((BASE / "sources.json").read_text())
    validate_original(BASE, original, sources)
    if args.input:
        if args.validate_only:
            raw = gzip.decompress(args.input.read_bytes())
            if sha(raw) != FIXED_DATA_SHA256:
                raise ValueError("Original price hash mismatch")
        else:
            prepare_spy(args.input, DIRECTORY, original, sources)
    spy, manifest = load_spy(DIRECTORY, original, sources)
    curves = {s: read_csv(BASE / (s + "-curve.csv")) for s in ("stable", "watch")}
    result, daily = analyze(spy, original, curves)
    csvs = output_csvs(result, daily)
    input_paths = ["results.json", "sources.json", "stable-curve.csv", "watch-curve.csv", "stable-open.json", "watch-open.json"]
    metadata = {
        "version": VERSION, "researchOnly": True, "start": original["start"], "end": original["end"],
        "input": manifest, "definitions": DEFINITIONS, "costRisk": original["costRisk"],
        "originalSourceHashes": original["sourceHashes"],
        "baseArtifactSHA256": {p: sha((BASE / p).read_bytes()) for p in input_paths},
        "analysisSourceSHA256": sha(Path(__file__).read_bytes()),
        "protocolSHA256": sha((DIRECTORY / "PROTOCOL.md").read_bytes()),
        "csvSHA256": {p: sha(text.encode()) for p, text in csvs.items()},
        "scenarios": result,
    }
    report = report_text(result)
    if args.validate_only:
        compare_nested(json.loads((DIRECTORY / "results.json").read_text()), metadata)
        for filename, digest in metadata["csvSHA256"].items():
            if sha((DIRECTORY / filename).read_bytes()) != digest:
                raise ValueError("Saved daily/metric CSV differs from recomputation: " + filename)
        if (DIRECTORY / "README.md").read_text() != report:
            raise ValueError("Saved report differs from recomputation")
        png = DIRECTORY / "regime-analysis.png"
        if png.exists():
            header = png.read_bytes()[:24]
            if header[:8] != b"\x89PNG\r\n\x1a\n" or min(struct.unpack(">II", header[16:24])) < 800:
                raise ValueError("Invalid research chart")
    else:
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        for filename, content in csvs.items():
            (DIRECTORY / filename).write_text(content)
        (DIRECTORY / "results.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
        (DIRECTORY / "README.md").write_text(report)
        if not args.no_chart:
            render_chart(DIRECTORY, result, daily)
    print(json.dumps({"validated": args.validate_only, "sessionsPerAccount": len(daily) // 2,
                      "fixedDatasetSHA256": manifest["datasetSHA256"],
                      "overall": {s: result[s]["summaries"][0] for s in result}}))


if __name__ == "__main__":
    main()
