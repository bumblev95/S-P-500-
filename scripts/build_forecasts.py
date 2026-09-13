"""Reproducible price scenarios, immutable issue records, and chronological checks.

No probabilities or investment recommendations are produced. This deliberately
small, fixed model must earn its place against the no-change benchmark.
"""
from __future__ import annotations

import csv
import json
import math
import re
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "trend-decay-v2-medium-long"
HORIZONS = (126, 252)
LONG_TERM_HORIZON = 756
MIN_TRAIN = 200
FIELDS = ("model", "symbol", "asOf", "issuedAt", "horizon", "anchor",
          "bear", "base", "bull", "direction", "dailyDrift", "volatility")


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def age_days(as_of, now):
    try:
        return (date.fromisoformat(now[:10]) - date.fromisoformat(as_of[:10])).days
    except (ValueError, TypeError):
        return None


def direction(change):
    return "up" if change > .02 else "down" if change < -.02 else "neutral"


SECTOR_EXIT_PE = {
    "Communication Services": 19.0, "Consumer Cyclical": 18.0,
    "Consumer Defensive": 19.0, "Energy": 13.0, "Financial Services": 14.0,
    "Healthcare": 18.0, "Industrials": 18.0, "Real Estate": 18.0,
    "Technology": 22.0, "Utilities": 17.0, "Basic Materials": 15.0,
}


def long_term_scenario(price_row, fundamental):
    """Three-year valuation scenarios, deliberately not a direction forecast.

    Forward/trailing EPS, observed growth and today's multiple are all explicit.
    Growth fades each year and the exit multiple moves toward a fixed sector norm.
    """
    price = number(price_row.get("close"))
    forward_eps = number(fundamental.get("forwardEps"))
    trailing_eps = number(fundamental.get("trailingEps"))
    eps = forward_eps if forward_eps and forward_eps > 0 else trailing_eps
    eps_source = "forwardEps" if forward_eps and forward_eps > 0 else "trailingEps"
    stated_pe = number(fundamental.get("forwardPE" if eps_source == "forwardEps" else "trailingPE"))
    current_pe = stated_pe if stated_pe and 2 <= stated_pe <= 200 else price / eps if price and eps else None
    observed = [number(fundamental.get(k)) for k in ("earningsGrowth", "revenueGrowth")]
    observed = [v for v in observed if v is not None and -1 < v < 5]
    if not price or not eps or not current_pe or not observed:
        return None
    near_growth = max(-.20, min(.30, sum(observed) / len(observed)))
    terminal_growth = .04
    base_growth = [near_growth, .55 * near_growth + .45 * terminal_growth, terminal_growth]
    sector = str(fundamental.get("sector") or "")
    normal_pe = SECTOR_EXIT_PE.get(sector, 18.0)
    # The base case never assumes multiple expansion. Expensive stocks move
    # toward a sector norm; already-cheaper stocks retain today's multiple.
    base_exit = max(8., min(35., min(current_pe, .45 * current_pe + .55 * normal_pe)))

    def case(name, growth_shift, multiple_factor):
        growth = [max(-.35, min(.40, g + growth_shift)) for g in base_growth]
        projected_eps = eps
        # Forward EPS represents year one already; trailing EPS still needs all
        # three annual steps to reach the same three-year endpoint.
        applied_growth = growth[1:] if eps_source == "forwardEps" else growth
        for g in applied_growth:
            projected_eps *= 1 + g
        exit_pe = max(6., min(45., base_exit * multiple_factor))
        value = projected_eps * exit_pe
        return {"name": name, "value": value, "return": value / price - 1,
                "eps": projected_eps, "exitPE": exit_pe,
                "annualGrowth": growth, "appliedGrowth": applied_growth}

    cases = {
        "bear": case("Bear", -.10, .75),
        "base": case("Base", 0., 1.),
        "bull": case("Bull", .08, 1.20),
    }
    if not cases["bear"]["value"] <= cases["base"]["value"] <= cases["bull"]["value"]:
        return None
    return {"horizon": LONG_TERM_HORIZON, "years": 3, "anchor": price,
            "epsSource": eps_source, "startingEps": eps, "currentPE": current_pe,
            "observedGrowth": observed, "terminalGrowth": terminal_growth,
            "sector": sector or None, "sectorNormalPE": normal_pe, "cases": cases,
            "method": "Growth fades toward 4%; base exit P/E never expands and compresses toward a fixed sector norm when elevated.",
            "warning": "Valuation scenarios, not probabilities or a three-year direction forecast."}


def predict(row, horizon):
    price = number(row.get("close"))
    vol = number(row.get("volatility4m"))
    components = []
    for field, days, weight in (("return1m", 21, .5), ("return3m", 63, .3),
                                ("return6m", 126, .2)):
        value = number(row.get(field))
        if value is not None and value > -1:
            components.append((math.log1p(value) / days, weight))
    # No invented default prices, returns, or volatility for missing inputs.
    if not price or price <= 0 or vol is None or not 0 <= vol <= 5 or len(components) < 2:
        return None
    momentum = sum(v * w for v, w in components) / sum(w for _, w in components)
    drift = max(-.6 / 252, min(.6 / 252, .35 * momentum))
    center = drift * 63 * (1 - math.exp(-horizon / 63))
    width = vol * math.sqrt(horizon / 252)
    base = price * math.exp(center)
    return {"horizon": horizon, "anchor": price, "bear": price * math.exp(center - width),
            "base": base, "bull": price * math.exp(center + width),
            "return": base / price - 1, "direction": direction(base / price - 1),
            "dailyDrift": drift, "volatility": vol}


def clean_history(items):
    by_date = {}
    for item in items:
        d, p = str(item.get("date", ""))[:10], number(item.get("close"))
        try:
            date.fromisoformat(d)
        except ValueError:
            continue
        if p is not None and p > 0:
            by_date[d] = {"date": d, "close": p, "volume": number(item.get("volume"))}
    return [by_date[d] for d in sorted(by_date)]


def snapshot(history, end):
    """Every input is sliced at the forecast origin, never at the dataset end."""
    past = history[:end + 1]
    prices = [p["close"] for p in past]
    row = {"close": prices[-1], "date": past[-1]["date"]}
    for field, days in (("return1m", 21), ("return3m", 63), ("return6m", 126)):
        row[field] = prices[-1] / prices[-1 - days] - 1 if len(prices) > days else None
    recent = prices[-85:]
    rets = [b / a - 1 for a, b in zip(recent, recent[1:])]
    row["volatility4m"] = statistics.stdev(rets) * math.sqrt(252) if len(rets) >= 24 else None
    return row


def metrics(pairs):
    if not pairs:
        return {"n": 0, "maePct": None, "baselineMaePct": None, "directionAccuracy": None,
                "rangeCoverage": None}
    n = len(pairs)
    return {"n": n,
            "maePct": sum(abs(p["base"] / actual - 1) for p, actual in pairs) / n,
            "baselineMaePct": sum(abs(p["anchor"] / actual - 1) for p, actual in pairs) / n,
            "directionAccuracy": sum(p["direction"] == direction(actual / p["anchor"] - 1)
                                     for p, actual in pairs) / n,
            "rangeCoverage": sum(p["bear"] <= actual <= p["bull"] for p, actual in pairs) / n}


def backtest(history, horizon):
    # Nonoverlapping outcomes; keep the same fixed model at every origin.
    pairs = []
    for end in range(MIN_TRAIN - 1, len(history) - horizon, horizon):
        pred = predict(snapshot(history, end), horizon)
        if pred:
            pairs.append((pred, history[end + horizon]["close"]))
    result = metrics(pairs)
    result["firstDate"] = history[MIN_TRAIN - 1]["date"] if pairs else None
    result["lastDate"] = history[-1]["date"] if pairs else None
    return result


def archive_records(directory, records):
    """First issued record wins for a model/symbol/origin/horizon."""
    by_month = {}
    for record in records:
        by_month.setdefault(record["asOf"][:7], []).append(record)
    for month, incoming in by_month.items():
        path = directory / (month + ".csv")
        existing = read_csv(path) if path.exists() else []
        key = lambda r: (r["model"], r["symbol"], r["asOf"], str(r["horizon"]))
        seen = {key(r) for r in existing}
        additions = []
        for record in incoming:
            if key(record) not in seen:
                additions.append(record)
                seen.add(key(record))
        if not additions:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".csv.tmp")
        with temp.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(existing + additions)
        temp.replace(path)


def read_archive(directory):
    records = []
    for path in sorted(directory.glob("*.csv")):
        records.extend(read_csv(path))
    return records


def score_issued(records, history, horizon):
    """Evaluate first-issued forecasts in original share units; skip revisions."""
    dates = {item["date"]: i for i, item in enumerate(history)}
    pairs, pending, revised, late = [], 0, 0, 0
    for record in records:
        if record["model"] != MODEL or int(record["horizon"]) != horizon:
            continue
        idx = dates.get(record["asOf"])
        if idx is None or idx + horizon >= len(history):
            pending += 1
            continue
        target = history[idx + horizon]
        if target["date"] <= record["issuedAt"][:10]:
            late += 1
            continue
        anchor = float(record["anchor"])
        # A split/provider correction must not become a fictitious forecast error.
        if abs(history[idx]["close"] / anchor - 1) > .005:
            revised += 1
            continue
        pred = {**record, **{k: float(record[k]) for k in ("anchor", "bear", "base", "bull")}}
        pairs.append((pred, target["close"]))
    return {**metrics(pairs), "pending": pending, "revised": revised, "late": late}


def build(root=ROOT, now=None):
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    price_path = root / "prices/latest_prices.csv"
    rows = read_csv(price_path)
    published_path = root / "forecasts/latest.json"
    try:
        published = json.loads(published_path.read_text(encoding="utf-8")).get("stocks", {})
    except (OSError, ValueError, TypeError):
        published = {}
    fundamental_path = root / "fundamentals/latest_fundamentals.csv"
    fundamentals = {str(r.get("symbol", "")).strip().upper(): r
                    for r in read_csv(fundamental_path)} if fundamental_path.exists() else {}
    archive = root / "forecasts/archive"
    existing = read_archive(archive)
    records_by_symbol = {}
    for record in existing:
        records_by_symbol.setdefault(record["symbol"], []).append(record)
    entries, new_records = {}, []
    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}", symbol):
            continue
        as_of = str(row.get("date", ""))[:10]
        age = age_days(as_of, now)
        fresh = age is not None and 0 <= age <= 5
        predictions = {str(h): predict(row, h) for h in HORIZONS}
        history_path = root / "prices/history" / (symbol + ".json")
        history = []
        if history_path.exists():
            raw = json.loads(history_path.read_text(encoding="utf-8"))
            history = clean_history(raw.get("prices", []))
            history = [p for p in history if p["date"] <= as_of]
        elif symbol in published:
            # A local/manual rebuild may not have the Actions-only history cache.
            # Preserve the already published observations instead of erasing charts.
            history = clean_history(published[symbol].get("history", []))
            history = [p for p in history if p["date"] <= as_of]
        # History and snapshot have to describe the same last close.
        price = number(row.get("close"))
        if history and (not price or price <= 0 or history[-1]["date"] != as_of or
                        abs(history[-1]["close"] / price - 1) > .005):
            history = []
        previous = records_by_symbol.get(symbol, [])
        outcomes = {str(h): score_issued(previous, history, h) for h in HORIZONS}
        for h in HORIZONS:
            if fresh and predictions[str(h)] and not any(
                    r["model"] == MODEL and r["asOf"] == as_of and int(r["horizon"]) == h
                    for r in previous):
                outcomes[str(h)]["pending"] += 1
        checks = {str(h): backtest(history, h) for h in HORIZONS}
        prior = {}
        for h in HORIZONS:
            candidates = [r for r in previous if r["model"] == MODEL and
                          int(r["horizon"]) == h and r["asOf"] < as_of]
            if candidates:
                last = max(candidates, key=lambda r: (r["asOf"], r["issuedAt"]))
                prior[str(h)] = {"asOf": last["asOf"], "direction": last["direction"]}
        entries[symbol] = {
            "symbol": symbol, "asOf": as_of, "sourceUpdatedAt": row.get("updatedAt"),
            "source": row.get("source", ""), "fresh": fresh,
            "status": "ready" if fresh and all(predictions.values()) else
                      "stale" if not fresh else "missing",
            "price": number(row.get("close")), "predictions": predictions,
            "longTermScenario": long_term_scenario(row, fundamentals.get(symbol, {})),
            "inputs": {k: number(row.get(k)) for k in
                       ("return1m", "return3m", "return6m", "ma20", "ma50", "ma200",
                        "volume", "avgVolume3m", "volatility4m")},
            "history": history[-253:], "historyCount": len(history),
            "backtest": checks, "issued": outcomes, "previous": prior,
        }
        if fresh:
            for h, pred in predictions.items():
                if pred:
                    new_records.append({k: v for k, v in
                                        {"model": MODEL, "symbol": symbol, "asOf": as_of,
                                         "issuedAt": now, **pred}.items() if k in FIELDS})
    archive_records(archive, new_records)
    payload = {"schemaVersion": 1, "model": MODEL, "generatedAt": now,
               "method": "Fixed damped momentum; volatility scenarios, not calibrated probabilities.",
               "horizons": list(HORIZONS), "longTermHorizon": LONG_TERM_HORIZON,
               "longTermMethod": "Fundamental Bear/Base/Bull valuation scenario with growth fade and no base-case P/E expansion; not a direction model.",
               "stocks": entries}
    atomic_json(root / "forecasts/latest.json", payload)
    print(f"Forecasts: {len(entries)} symbols; "
          f"{sum(e['status'] == 'ready' for e in entries.values())} ready; "
          f"{sum(bool(e['history']) for e in entries.values())} with history.")
    return payload


if __name__ == "__main__":
    build()
