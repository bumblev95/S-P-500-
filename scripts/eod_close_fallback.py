"""Recover one missing completed daily bar, never an entire price history.

Nasdaq's public historical response must match the existing Yahoo symbol,
three preceding closes and the incomplete bar's OHLC at cent precision. The
source response is retained as evidence with the public price snapshot.
"""
from __future__ import annotations

import hashlib
import base64
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pandas as pd

from eod_publication import latest_closed_session, timestamp

SOURCE = "Yahoo EOD history + Nasdaq historical EOD bar"


def nasdaq_symbol(symbol):
    value = re.sub(r"-([AB])$", r".\1", symbol)
    if not re.fullmatch(r"[A-Z][A-Z0-9]*(?:\.[AB])?", value):
        raise ValueError("Not a supported US equity symbol")
    return value


def source_url(symbol, as_of):
    start = date.fromisoformat(as_of) - timedelta(days=14)
    query = urllib.parse.urlencode({"assetclass": "stocks", "fromdate": start.isoformat(),
                                   "todate": as_of, "limit": 20})
    return f"https://api.nasdaq.com/api/quote/{nasdaq_symbol(symbol)}/historical?{query}"


def candidate(meta, frame, as_of):
    return (meta.get("currency") == "USD" and meta.get("instrumentType") == "EQUITY"
            and meta.get("exchangeTimezoneName") == "America/New_York"
            and not frame.empty and frame.index.is_unique and frame.index.is_monotonic_increasing
            and frame.index[-1].date().isoformat() == as_of
            and "Close" in frame and pd.isna(frame.iloc[-1]["Close"]))


def price(value):
    if not isinstance(value, str) or not re.fullmatch(r"\$[0-9,]+(?:\.[0-9]+)?", value):
        raise ValueError("Expected a Nasdaq USD historical price")
    result = float(value[1:].replace(",", ""))
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Invalid Nasdaq historical price")
    return result


def cents(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid Yahoo comparison price") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("Invalid Yahoo comparison price")
    return number.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def encode_evidence(evidence):
    # An opaque, comma-free final CSV column also works with simple CSV readers.
    return base64.urlsafe_b64encode(canonical(evidence)).decode()


def decode_evidence(value):
    return json.loads(base64.b64decode(value, altchars=b"-_", validate=True))


def checked_bar(payload, symbol, frame, as_of):
    data = payload.get("data") or {}
    if payload.get("status", {}).get("rCode") != 200 or data.get("symbol") != nasdaq_symbol(symbol):
        raise ValueError("Wrong symbol or failed Nasdaq historical response")
    rows = {}
    for item in (data.get("tradesTable") or {}).get("rows") or []:
        day = datetime.strptime(item["date"], "%m/%d/%Y").date().isoformat()
        if day in rows or day > as_of:
            raise ValueError("Duplicate or future Nasdaq historical bar")
        rows[day] = item
    if as_of not in rows:
        raise ValueError("Nasdaq has no completed bar for the required session")
    previous = frame.loc[frame.index.date < date.fromisoformat(as_of), "Close"].dropna().tail(3)
    previous_session = latest_closed_session(as_of + "T12:00:00Z")
    if len(previous) != 3 or previous.index[-1].date().isoformat() != previous_session:
        raise ValueError("Insufficient current Yahoo history to verify replacement")
    for day, close in previous.items():
        other = rows.get(day.date().isoformat(), {})
        if cents(close) != cents(price(other.get("close"))):
            raise ValueError("Nasdaq and Yahoo historical price bases disagree")
    row = rows[as_of]
    bar = {key.title(): price(row.get(key)) for key in ("open", "high", "low", "close")}
    if not bar["Low"] <= min(bar["Open"], bar["Close"]) <= max(bar["Open"], bar["Close"]) <= bar["High"]:
        raise ValueError("Inconsistent Nasdaq historical OHLC")
    for key in ("Open", "High", "Low"):
        if cents(frame.iloc[-1].get(key)) != cents(bar[key]):
            raise ValueError("Nasdaq and Yahoo current-session OHLC disagree")
    volume = row.get("volume")
    if not isinstance(volume, str) or not re.fullmatch(r"[0-9,]+", volume):
        raise ValueError("Missing Nasdaq historical volume")
    bar["Volume"] = int(volume.replace(",", ""))
    if bar["Volume"] <= 0:
        raise ValueError("Invalid Nasdaq historical volume")
    # On the latest session there are no subsequent dividends/splits to adjust.
    bar["Adj Close"] = bar["Close"]
    return bar


def recover(symbol, meta, frame, as_of):
    if not candidate(meta, frame, as_of):
        return frame, None
    if meta.get("symbol") != symbol:
        raise ValueError("Yahoo symbol identity mismatch")
    url = source_url(symbol, as_of)
    request = urllib.request.Request(url, headers={"User-Agent": "PublicStockDashboard/1.0",
                                                  "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    bar = checked_bar(payload, symbol, frame, as_of)
    evidence = {"provider": "Nasdaq historical EOD", "symbol": symbol, "date": as_of,
                "sourceUrl": url, "retrievedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "responseSha256": hashlib.sha256(canonical(payload)).hexdigest(), "response": payload,
                "yahooMeta": {k: meta[k] for k in ("symbol", "currency", "instrumentType", "exchangeTimezoneName")},
                "yahooOhlc": {k: float(frame.iloc[-1][k]) for k in ("Open", "High", "Low")}}
    recovered = frame.copy()
    for key, value in bar.items():
        recovered.loc[recovered.index[-1], key] = value
    return recovered, evidence


def verify_evidence(evidence, symbol, as_of, collected, history):
    """Recheck recorded evidence before the all-symbol publication transaction."""
    if (evidence.get("provider") != "Nasdaq historical EOD"
            or nasdaq_symbol(evidence.get("symbol", "")) != nasdaq_symbol(symbol)
            or evidence.get("date") != as_of or evidence.get("sourceUrl") != source_url(symbol, as_of)
            or timestamp(evidence["retrievedAt"]) > timestamp(collected)
            or latest_closed_session(evidence["retrievedAt"]) != as_of
            or hashlib.sha256(canonical(evidence["response"])).hexdigest() != evidence.get("responseSha256")):
        raise ValueError("Invalid or stale secondary EOD evidence")
    frame = pd.DataFrame([{k.title(): v for k, v in item.items() if k in ("close", "open", "high", "low", "volume")}
                          for item in history], index=pd.to_datetime([item["date"] for item in history]))
    for key, value in evidence["yahooOhlc"].items():
        frame.loc[frame.index[-1], key] = value
    frame.loc[frame.index[-1], "Close"] = float("nan")
    meta = evidence["yahooMeta"]
    if meta.get("symbol") != evidence["symbol"] or not candidate(meta, frame, as_of):
        raise ValueError("Invalid original Yahoo context for secondary EOD bar")
    bar = checked_bar(evidence["response"], symbol, frame, as_of)
    for key in ("Close", "Open", "High", "Low", "Volume"):
        if round(float(history[-1].get(key.lower(), -1)), 6) != round(bar[key], 6):
            raise ValueError("Recorded secondary EOD bar and history disagree")
