"""Refresh the two research snapshots using Python 3.9+ and the standard library."""
import argparse
import bisect
import csv
import datetime as dt
import html
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PATHOS = "https://pathosinvestments.com/congress/nvda"
MARKET = "https://steadyshares.com/politicians/leaderboard"
FIRST_DAY = dt.date(2024, 1, 1)
RANK_METHOD = ("Purchases only. From the first close on or after filing to the as-of close, compared "
               "with SPY over matching periods. Equal-weight, split-adjusted prices excluding dividends. "
               "Holding periods vary. Sorted locally by win rate or average excess percentage points.")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fetch(url):
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Congress research scorecard refresh)"})
            with urlopen(req, timeout=25) as response:
                return response.read().decode("utf-8-sig")
        except OSError:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def text_only(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def number(value):
    n = float(value)
    require(math.isfinite(n), "Invalid numeric value")
    return n


def source_date(text, fmt="%b %d, %Y"):
    return dt.datetime.strptime(text, fmt).date()


class TradeRows(HTMLParser):
    """Read the upstream's labeled trade cells and preserve each row's own filing link."""
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and attrs.get("id", "").startswith("t-"):
            self.row = {}
        elif self.row is not None and tag == "td":
            self.cell = {"text": [], "attrs": attrs, "href": None}
            self.row[attrs.get("data-l", "")] = self.cell
        elif self.cell is not None and tag == "a":
            self.cell["href"] = attrs.get("href")

    def handle_data(self, data):
        if self.cell is not None and data.strip():
            self.cell["text"].append(data.strip())

    def handle_endtag(self, tag):
        if tag == "td":
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def event_from(row):
    member_cell = row["Member"]
    member = member_cell["attrs"]["data-v"]
    details = " ".join(member_cell["text"])
    if "Rep. " in details:
        chamber, pattern = "house", r"https://disclosures-clerk\.house\.gov/public_disc/ptr-pdfs/\d{4}/\d+\.pdf"
    else:
        require("Sen. " in details, "Unknown chamber")
        chamber, pattern = "senate", r"https://efdsearch\.senate\.gov/search/view/(?:ptr|paper)/[\w-]+/"
    url = row["Source"]["href"]
    require(re.fullmatch(pattern, url or ""), "Missing official filing URL for " + member)
    owner = re.search(r"·\s*(SP|JT|DC)\b", details)
    action, *description = row["Action"]["text"]
    match = re.fullmatch(r"(BUY|SELL)(?: \((partial|full)\))?", action)
    require(match, "Unrecognized transaction: " + action)
    traded = source_date(row["Traded"]["text"][0])
    filed = source_date(row["Disclosed"]["text"][0])
    require(filed >= traded, "Disclosure predates trade for " + member)
    score = row["This trade vs SPY (90 d)"]["text"][0]
    if score != "—":
        require(re.fullmatch(r"[+−-]?[\d.]+%", score), "Unexpected 90-day score")
    opt = " ".join(description)
    event = {"member": member, "tradeDate": str(traded), "disclosedDate": str(filed),
             "side": match[1].lower(), "owner": {"SP":"spouse", "JT":"joint", "DC":"dependent"}.get(owner[1] if owner else None, "unspecified"),
             "chamber":chamber, "amount":row["Reported amount"]["text"][0],
             "partial":match[2] == "partial", "option":"option" in opt.lower(),
             "excess90d":None if score == "—" else number(score[:-1].replace("−", "-")), "filingUrl":url}
    if event["option"]:
        event["optionDescription"] = opt
    return event


def yahoo_history(as_of):
    # Fixed start keeps historic outcomes reproducible as the snapshot advances.
    def midnight(day):
        return int(dt.datetime.combine(day, dt.time(), dt.timezone.utc).timestamp())
    query = urlencode({"period1":midnight(FIRST_DAY), "period2":midnight(as_of + dt.timedelta(days=1)), "interval":"1d"})
    for host in ("query2", "query1"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/NVDA?{query}"
        try:
            chart = json.loads(fetch(url))["chart"]["result"][0]
            require(chart["meta"]["symbol"] == "NVDA", "Unexpected quote symbol")
            timestamps, closes = chart["timestamp"], chart["indicators"]["quote"][0]["close"]
            require(len(timestamps) == len(closes), "Truncated quote series")
            prices = {}
            for t, c in zip(timestamps, closes):
                day = dt.datetime.fromtimestamp(t, dt.timezone.utc).date()
                if FIRST_DAY <= day <= as_of and c is not None:
                    prices[day] = number(c)
            require(prices and all(c > 0 for c in prices.values()), "Invalid daily closes")
            return prices, url
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            if host == "query1":
                raise


def nvda_snapshot():
    page = fetch(PATHOS)
    as_of = dt.date.fromisoformat(re.search(r"Built (\d{4}-\d{2}-\d{2})", page)[1])
    headline = re.search(r"All time \(filings since 2024\): ([\d,]+) members, ([\d,]+) trades", text_only(page))
    require(headline and "Who in Congress traded Nvidia (NVDA)?" in text_only(page), "Invalid NVDA source")
    parser = TradeRows(); parser.feed(page)
    events = [event_from(r) for r in parser.rows]
    require(len(events) == int(headline[2].replace(",","")) > 0 and len({r["member"] for r in events}) == int(headline[1].replace(",","")), "Incomplete NVDA table")
    prices, url = yahoo_history(as_of)
    days = sorted(prices)
    # Require every published session from the chart, including recent closes.
    chart_data = json.loads(re.search(r'<script[^>]+id="cdata"[^>]*>(.*?)</script>', page, re.S)[1])
    reference_days = {dt.date.fromisoformat(day) for day, _ in chart_data["px"] if str(FIRST_DAY) <= day <= str(as_of)}
    require(reference_days and reference_days <= set(days) and (as_of-days[-1]).days <= 5, "Incomplete NVDA price history")
    def first_close(day):
        i = bisect.bisect_left(days, day)
        if i < len(days) and (days[i] - day).days <= 4:
            return prices[days[i]]
        return None
    eval_count = 0
    for r in events:
        trade = dt.date.fromisoformat(r["tradeDate"])
        finish = trade + dt.timedelta(days=90)
        r["absolute90dPct"] = None
        if r["option"] or trade < FIRST_DAY or finish > as_of:
            continue
        start, end = first_close(trade), first_close(finish)
        if start is not None and end is not None:
            r["absolute90dPct"] = round(100*(end/start-1), 8)
            eval_count += 1
    require(eval_count > 0 and any(r["excess90d"] is not None for r in events), "No scored history")
    return {"symbol":"NVDA","asOf":str(as_of),"source":"Pathos Investments","sourceUrl":PATHOS,"events":events,
            "absolute90dMethod":{"sourceUrl":url,"start":"First trading close on or after trade date",
            "end":"First trading close on or after trade date + 90 calendar days, through "+str(as_of),
            "measure":"Signed percentage price change of NVDA regardless of side, split-adjusted, excluding dividends",
            "coverageStart":str(days[0]),"coverageEnd":str(days[-1]),"sessions":len(days)},
            "history":[{"date":str(d),"close":round(prices[d],6)} for d in days]}


def market_snapshot(previous):
    raw = list(csv.DictReader(io.StringIO(fetch(MARKET + "/data.csv"))))
    summary = text_only(fetch(MARKET))
    expected = re.search(r"of their purchases could; ([\d,]+) of [\d,]+ were",summary)
    require(expected and int(expected[1].replace(",","")) == len(raw) > 0, "Incomplete market leaderboard")
    previous_names = {r["name"]:r.get("nameKo") for r in previous.get("rows", [])}
    dates = {(r["as_of"],r["trades_from"],r["computed_on"]) for r in raw}
    require(len(dates)==1, "Mixed market snapshot dates")
    as_of, start, computed = tuple(map(dt.date.fromisoformat, dates.pop()))
    require(start <= as_of <= computed and "priced to the close of "+as_of.strftime("%d %b %Y").lstrip("0") in summary, "Market HTML/CSV date mismatch")
    rows = []
    for rank, r in enumerate(raw,1):
        name, n, wins = r["member"], int(r["purchases_priced"]), int(r["purchases_beating_spy"])
        require(name and int(r["rank"]) == rank and 0 <= wins <= n and n>=5, "Invalid market row")
        require(r["chamber"] in {"house","senate"}, "Invalid market chamber")
        row = {"name":name,"party":r["party"],"chamber":r["chamber"].title(),"wins":wins,"count":n,
               "excess":number(r["ahead_of_spy_points"]), "filingReturn":number(r["avg_move_since_filing_pct"]),
               "tradeReturn":number(r["avg_move_since_trade_pct"]), "benchmarkReturn":number(r["spy_same_windows_since_filing_pct"]),
               "medianDelay":number(r["median_filing_delay_days"])}
        if previous_names.get(name):
            row["nameKo"]=previous_names[name]
        rows.append(row)
    require(len({r["name"] for r in rows})==len(rows),"Duplicate members in market table")
    return {"source":"SteadyShares","sourceUrl":MARKET,"sourceCsv":MARKET+"/data.csv","license":"CC BY 4.0",
            "licenseUrl":"https://creativecommons.org/licenses/by/4.0/","asOf":str(as_of),"computed":str(computed),
            "tradeStart":str(start),"benchmark":"SPY","method":RANK_METHOD,"rows":rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1]/"data"/"congress")
    args = parser.parse_args()
    target = args.output_dir
    target.mkdir(parents=True, exist_ok=True)
    snapshots = []
    # Stage only after all sources validate, so a partial refresh leaves both last-good datasets intact.
    for name, builder in [("NVDA.json", lambda _: nvda_snapshot()), ("market.json", market_snapshot)]:
        path=target/name
        previous=json.loads(path.read_text()) if path.exists() else {}
        snapshot=builder(previous)
        require(not previous or snapshot["asOf"] >= previous["asOf"], f"{name}: stale provider date")
        if previous.get("computed") and snapshot["asOf"] == previous.get("asOf"):
            require(snapshot["computed"] >= previous["computed"], f"{name}: stale provider computation")
        snapshots.append((path, snapshot))
    for path, snapshot in snapshots:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target, delete=False) as f:
            json.dump(snapshot,f,ensure_ascii=False,separators=(",",":"),allow_nan=False)
            f.write("\n")
        os.chmod(f.name, 0o644)
        os.replace(f.name,path)
        print(f'{path.name} as of {snapshot["asOf"]}')


if __name__ == "__main__":
    main()
