"""Dated, reviewed security identities; never infer aliases from provider errors."""
from __future__ import annotations

import hashlib
import json
import math
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from eod_close_fallback import canonical, cents, nasdaq_symbol, price, source_url
from eod_publication import latest_closed_session, timestamp

SOURCE = "Yahoo EOD via verified symbol transition"
PROVIDER = "Yahoo chart with verified symbol transition"

# Same issuer (CIK 2041610), same Class B common stock. WBD's cash merger is
# deliberately not an alias. Registry changes require review and dated evidence.
TRANSITIONS = {
    "PSKY": {
        "effectiveDate": "2026-10-06", "yahooSymbol": "SKYD", "nasdaqSymbol": "SKYD",
        "exchangeName": "NYQ", "longName": "Skydance Corporation", "cik": "2041610",
        "security": "Class B common stock",
        "sourceUrl": "https://ir.paramount.com/node/73436/html",
        "announcementUrl": "https://ir.paramount.com/static-files/36b6ca19-67e4-4787-94ee-8c4c1373e0ac",
    },
}
LAST_TRADING_SESSIONS = {
    "WBD": ("2026-10-05", "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-710"),
}


def transition(symbol, as_of):
    record = TRANSITIONS.get(symbol)
    return dict(record) if record and as_of >= record["effectiveDate"] else None


def assert_trading_session(symbol, as_of):
    ended = LAST_TRADING_SESSIONS.get(symbol)
    if ended and as_of > ended[0]:
        raise ValueError(f"{symbol}: exchange trading ended {ended[0]}; universe update required for {as_of}")


def chart_url(symbol):
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=10y&interval=1d"


def history_hash(history):
    return hashlib.sha256(canonical(history)).hexdigest()


def published_anchors(path, symbol, as_of):
    # Prior published prices are identity checks only, never replacement prices.
    stock = json.loads(path.read_text(encoding="utf-8"))["stocks"][symbol]
    if stock.get("symbol") != symbol or stock.get("asOf", "") > as_of:
        raise ValueError("Invalid published symbol-transition anchor")
    history = stock.get("history", [])
    return [{"date": item["date"], "close": item["close"]}
            for item in history if item["date"] < as_of][-3:]


def check_context(meta, history, anchors, mapping, as_of):
    expected = {"symbol": mapping["yahooSymbol"], "currency": "USD", "instrumentType": "EQUITY",
                "exchangeTimezoneName": "America/New_York", "exchangeName": mapping["exchangeName"],
                "longName": mapping["longName"]}
    if any(meta.get(key) != value for key, value in expected.items()):
        raise ValueError("Mapped Yahoo security identity does not match the reviewed transition")
    days = [item["date"] for item in history]
    if not days or days != sorted(set(days)) or days[-1] != as_of:
        raise ValueError("Mapped Yahoo history must end at the completed session without duplicates")
    previous = latest_closed_session(as_of + "T12:00:00Z")
    prior = [item for item in history if item["date"] < as_of][-3:]
    if (len(anchors) != 3 or len(prior) != 3 or anchors[-1]["date"] != previous
            or [item["date"] for item in anchors] != [item["date"] for item in prior]):
        raise ValueError("Three current published anchors are required for a symbol transition")
    for original, current in zip(anchors, prior):
        if cents(original["close"]) != cents(current["close"]):
            raise ValueError("Mapped Yahoo history and published price bases disagree")
    bar = history[-1]
    values = {key: float(bar[key]) for key in ("open", "high", "low", "close", "volume")}
    if (any(not math.isfinite(v) or v <= 0 for v in values.values())
            or not values["low"] <= min(values["open"], values["close"])
            <= max(values["open"], values["close"]) <= values["high"]
            or values["volume"] != int(values["volume"])):
        raise ValueError("Mapped Yahoo completed OHLCV is missing or inconsistent")


def check_secondary(payload, mapping, history, as_of):
    data = payload.get("data") or {}
    if (payload.get("status", {}).get("rCode") != 200
            or data.get("symbol") != nasdaq_symbol(mapping["nasdaqSymbol"])):
        raise ValueError("Wrong mapped symbol or failed Nasdaq historical response")
    rows = {}
    for item in (data.get("tradesTable") or {}).get("rows") or []:
        day = datetime.strptime(item["date"], "%m/%d/%Y").date().isoformat()
        if day in rows or day > as_of:
            raise ValueError("Duplicate or future mapped Nasdaq historical bar")
        rows[day] = item
    if as_of not in rows:
        raise ValueError("Mapped Nasdaq has no completed bar for the required session")
    for key in ("open", "high", "low", "close"):
        if cents(price(rows[as_of].get(key))) != cents(history[-1][key]):
            raise ValueError("Mapped Nasdaq and Yahoo completed OHLC disagree")
    volume = rows[as_of].get("volume", "")
    if not isinstance(volume, str) or not volume.replace(",", "").isdigit() or int(volume.replace(",", "")) <= 0:
        raise ValueError("Mapped Nasdaq completed volume is missing")


def frame_history(frame):
    return [{"date": day.date().isoformat(),
             **{key.lower(): float(row[key]) for key in ("Open", "High", "Low", "Close", "Volume")}}
            for day, row in frame.iterrows() if pd.notna(row.get("Close"))]


def attest(symbol, meta, frame, as_of, anchors):
    mapping = transition(symbol, as_of)
    if mapping is None:
        raise ValueError("No reviewed symbol transition for this session")
    history = frame_history(frame)
    check_context(meta, history, anchors, mapping, as_of)
    url = source_url(mapping["nasdaqSymbol"], as_of)
    request = urllib.request.Request(url, headers={"User-Agent": "PublicStockDashboard/1.0",
                                                  "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    check_secondary(payload, mapping, history, as_of)
    return {"provider": PROVIDER, "symbol": symbol, "date": as_of,
            "transition": mapping, "yahooSymbol": mapping["yahooSymbol"],
            "sourceUrl": chart_url(mapping["yahooSymbol"]), "yahooMeta": meta,
            "anchors": anchors, "nasdaqSourceUrl": url, "response": payload,
            "responseSha256": hashlib.sha256(canonical(payload)).hexdigest(),
            "retrievedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def verify_evidence(evidence, symbol, as_of, collected, history):
    mapping = transition(symbol, as_of)
    if (mapping is None or evidence.get("provider") != PROVIDER or evidence.get("symbol") != symbol
            or evidence.get("transition") != mapping or evidence.get("date") != as_of
            or evidence.get("yahooSymbol") != mapping["yahooSymbol"]
            or evidence.get("sourceUrl") != chart_url(mapping["yahooSymbol"])
            or evidence.get("nasdaqSourceUrl") != source_url(mapping["nasdaqSymbol"], as_of)
            or timestamp(evidence["retrievedAt"]) > timestamp(collected)
            or latest_closed_session(evidence["retrievedAt"]) != as_of
            or hashlib.sha256(canonical(evidence["response"])).hexdigest() != evidence.get("responseSha256")
            or history_hash(history) != evidence.get("historySha256")):
        raise ValueError("Invalid or stale verified symbol-transition evidence")
    check_context(evidence["yahooMeta"], history, evidence["anchors"], mapping, as_of)
    check_secondary(evidence["response"], mapping, history, as_of)
