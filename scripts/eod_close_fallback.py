"""Recover a short trailing gap in completed daily bars.

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
from functools import lru_cache
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
            and not frame.empty and frame.index.normalize().is_unique and frame.index.is_monotonic_increasing
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


def historical_rows(payload, symbol, as_of):
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
    return rows


def checked_bar(payload, symbol, frame, as_of):
    rows = historical_rows(payload, symbol, as_of)
    previous = frame.loc[frame.index.date < date.fromisoformat(as_of), "Close"].dropna().tail(3)
    previous_session = latest_closed_session(as_of + "T12:00:00Z")
    if len(previous) != 3 or previous.index[-1].date().isoformat() != previous_session:
        raise ValueError("Insufficient current Yahoo history to verify replacement")
    for day, close in previous.items():
        other = rows.get(day.date().isoformat(), {})
        if cents(close) != cents(price(other.get("close"))):
            raise ValueError("Nasdaq and Yahoo historical price bases disagree")
    bar = completed_bar(rows[as_of])
    for key in ("Open", "High", "Low"):
        if cents(frame.iloc[-1].get(key)) != cents(bar[key]):
            raise ValueError("Nasdaq and Yahoo current-session OHLC disagree")
    return {**bar, "Adj Close": bar["Close"]}


def completed_bar(row):
    bar = {key.title(): price(row.get(key)) for key in ("open", "high", "low", "close")}
    if not bar["Low"] <= min(bar["Open"], bar["Close"]) <= max(bar["Open"], bar["Close"]) <= bar["High"]:
        raise ValueError("Inconsistent Nasdaq historical OHLC")
    volume = row.get("volume")
    if not isinstance(volume, str) or not re.fullmatch(r"[0-9,]+", volume):
        raise ValueError("Missing Nasdaq historical volume")
    bar["Volume"] = int(volume.replace(",", ""))
    if bar["Volume"] <= 0:
        raise ValueError("Invalid Nasdaq historical volume")
    return bar


@lru_cache(maxsize=8)
def recent_sessions(as_of):
    import exchange_calendars as xcals

    end = date.fromisoformat(as_of)
    start = end - timedelta(days=18)
    calendar = xcals.get_calendar("XNYS", start=start - timedelta(days=10), end=end + timedelta(days=10))
    sessions = calendar.sessions_in_range(start.isoformat(), as_of)
    return tuple(day.strftime("%Y-%m-%d") for day in sessions)


def recovery_gap(frame, as_of):
    valid = frame["Close"].dropna()
    if valid.empty:
        raise ValueError("Yahoo has no overlapping history")
    last = valid.index[-1].date().isoformat()
    sessions = recent_sessions(as_of)
    gap = tuple(day for day in sessions if day > last)
    if not 1 <= len(gap) <= 5 or gap[-1] != as_of or last not in sessions:
        raise ValueError("Yahoo gap is outside the supported five-session window")
    prior = sessions[:sessions.index(last) + 1][-3:]
    if len(prior) != 3 or any(pd.Timestamp(day) not in valid.index for day in prior):
        raise ValueError("Insufficient contiguous Yahoo history to verify replacement")
    return prior, gap


def same_price(left, right):
    # Yahoo's binary quotes can straddle a half-cent that Nasdaq publishes
    # in decimal. Allow only the precision difference, not a price discrepancy.
    return (cents(left) == cents(right)
            or abs(Decimal(str(left)) - Decimal(str(right))) <= Decimal("0.0001"))


def checked_gap(payload, symbol, frame, as_of):
    rows = historical_rows(payload, symbol, as_of)
    prior, gap = recovery_gap(frame, as_of)
    for day in prior:
        if not same_price(frame.loc[pd.Timestamp(day), "Close"], price(rows.get(day, {}).get("close"))):
            raise ValueError("Nasdaq and Yahoo historical price bases disagree")
    bars, observations = {}, {}
    for day in gap:
        if day not in rows:
            raise ValueError(f"Nasdaq has no completed bar for {day}")
        index = pd.Timestamp(day)
        yahoo = frame.loc[index] if index in frame.index else {}
        original = {field: float(yahoo.get(field)) for field in ("Open", "High", "Low")
                    if pd.notna(yahoo.get(field))}
        if day == as_of and len(original) != 3:
            raise ValueError("Yahoo current-session OHLC is incomplete")
        bar = completed_bar(rows[day])
        if any(not same_price(value, bar[field]) for field, value in original.items()):
            raise ValueError("Nasdaq and Yahoo current-session OHLC disagree")
        observations[day] = original
        bars[day] = bar
    return bars, observations


def recover(symbol, meta, frame, as_of):
    if not candidate(meta, frame, as_of):
        return frame, None
    if meta.get("symbol") != symbol:
        raise ValueError("Yahoo symbol identity mismatch")
    original = frame
    frame = frame.copy()
    frame.index = frame.index.normalize()
    url = source_url(symbol, as_of)
    request = urllib.request.Request(url, headers={"User-Agent": "PublicStockDashboard/1.0",
                                                  "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    evidence = {"provider": "Nasdaq historical EOD", "symbol": symbol, "date": as_of,
                "sourceUrl": url, "retrievedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "responseSha256": hashlib.sha256(canonical(payload)).hexdigest(), "response": payload,
                "yahooMeta": {k: meta[k] for k in ("symbol", "currency", "instrumentType", "exchangeTimezoneName")}}
    last_valid = frame["Close"].last_valid_index()
    if last_valid is not None and last_valid.date().isoformat() == latest_closed_session(as_of + "T12:00:00Z"):
        bars = {as_of: checked_bar(payload, symbol, frame, as_of)}
        evidence["yahooOhlc"] = {k: float(frame.iloc[-1][k]) for k in ("Open", "High", "Low")}
    else:
        bars, observations = checked_gap(payload, symbol, frame, as_of)
        evidence["yahooGap"] = observations
    recovered = original.copy()
    times = {day.date().isoformat(): day for day in original.index}
    open_offset = original.index[-1] - original.index[-1].normalize()
    for day, bar in bars.items():
        index = times.get(day, pd.Timestamp(day) + open_offset)
        for key, value in bar.items():
            recovered.loc[index, key] = value
    recovered.loc[times[as_of], "Adj Close"] = bars[as_of]["Close"]
    return recovered.sort_index(), evidence


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
    published = frame.copy()
    if "yahooGap" in evidence:
        observations = evidence["yahooGap"]
        if not isinstance(observations, dict) or not 2 <= len(observations) <= 5 or as_of not in observations:
            raise ValueError("Invalid original Yahoo gap")
        for day, original in observations.items():
            index = pd.Timestamp(day)
            if index not in frame.index or not isinstance(original, dict) or set(original) - {"Open", "High", "Low"}:
                raise ValueError("Invalid original Yahoo gap observation")
            frame.loc[index, "Close"] = float("nan")
            for field in ("Open", "High", "Low"):
                frame.loc[index, field] = original.get(field, float("nan"))
        meta = evidence["yahooMeta"]
        if meta.get("symbol") != evidence["symbol"] or not candidate(meta, frame, as_of):
            raise ValueError("Invalid original Yahoo context for secondary EOD gap")
        bars, checked = checked_gap(evidence["response"], symbol, frame, as_of)
        if checked != observations:
            raise ValueError("Recorded Yahoo dates and secondary EOD gap disagree")
    else:
        for key, value in evidence["yahooOhlc"].items():
            frame.loc[frame.index[-1], key] = value
        frame.loc[frame.index[-1], "Close"] = float("nan")
        meta = evidence["yahooMeta"]
        if meta.get("symbol") != evidence["symbol"] or not candidate(meta, frame, as_of):
            raise ValueError("Invalid original Yahoo context for secondary EOD bar")
        bars = {as_of: checked_bar(evidence["response"], symbol, frame, as_of)}
    for day, bar in bars.items():
        for key in ("Close", "Open", "High", "Low", "Volume"):
            if round(float(published.loc[pd.Timestamp(day), key]), 6) != round(bar[key], 6):
                raise ValueError(f"Recorded secondary EOD bar and history disagree for {day}")
