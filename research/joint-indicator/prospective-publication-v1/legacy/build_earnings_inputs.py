"""Original company earnings releases, dated features, and immutable observations.

No SEC requests, API keys, present-day backfill, or analyst-consensus inference.
The explicit free-source pilot is NVDA/MSFT. Other issuers remain uncovered.
"""
import calendar
import csv
import hashlib
import json
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from build_forecasts import atomic_json

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ['quarterRevenueGrowth', 'quarterNetMargin', 'quarterEpsChange', 'nextQuarterRevenueGrowth']
MONTH = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?'
DATE = MONTH + r'\s+\d{1,2},\s+\d{4}'
PARSER_VERSION = 1


class ReleaseHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip = 0; self.text = []; self.tables = []
        self.table = None; self.row = None; self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.skip += 1
        if tag == 'table': self.table = []
        if tag == 'tr': self.row = []
        if tag in ('td', 'th'): self.cell = []

    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.skip = max(0, self.skip - 1)
        if tag in ('td', 'th') and self.cell is not None:
            if self.row is not None: self.row.append(' '.join(' '.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            if self.table is not None: self.table.append(self.row)
            self.row = None
        if tag == 'table' and self.table is not None:
            self.tables.append(self.table); self.table = None

    def handle_data(self, value):
        if not self.skip:
            self.text.append(value)
            if self.cell is not None: self.cell.append(value)


def iso(value):
    value=' '.join(value.replace('.', '').split())
    for fmt in ('%B %d, %Y','%b %d, %Y'):
        try:return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:pass
    raise ValueError('Invalid publication date')


def numbers(row):
    """Ignore currency-only cells, footnotes, and percent-change columns."""
    result = []
    for value in row[1:]:
        value = re.sub(r'[\s,$]', '', value).replace('\u2212', '-')
        if re.fullmatch(r'\(?-?\d+(?:\.\d+)?\)?', value):
            result.append(-float(value[1:-1]) if value.startswith('(') else float(value))
    return result


def labelled(table, labels):
    for row in table:
        label = re.sub(r'[\s:*]+', ' ', row[0]).strip().lower() if row else ''
        if label in labels and len(numbers(row)) >= 2: return numbers(row)
    raise ValueError('Missing comparable GAAP row: ' + '/'.join(labels))


def parse_release(symbol, fiscal_year, quarter, html, url):
    doc = ReleaseHTML(); doc.feed(html); text = ' '.join(' '.join(doc.text).split())
    guidance = None
    if symbol == 'NVDA':
        title = re.search(r'NVIDIA (?:(?:Announces|Reports) )?Financial Results for (?:First|Second|Third|Fourth) Quarter(?: and)?(?: Fiscal)?\s+(\d{4})', text, re.I)
        if not title or int(title[1]) != fiscal_year: raise ValueError('NVIDIA release identity mismatch')
        first = title.start(); snippet = text[first:first + 8000]
        published = re.search(DATE, snippet)
        ended = re.search(r'ended\s+(' + DATE + ')', snippet, re.I)
        table = next((t for t in doc.tables if any('GAAP' in ' '.join(r) and 'Non-GAAP' not in ' '.join(r) for r in t[:3])
                      and any(re.search(r'Q[1-4]FY', re.sub(r'\s+', '', ' '.join(r))) for r in t[:5])), None)
        if table is None: raise ValueError('Missing NVIDIA GAAP quarterly table')
        header = ' '.join(' '.join(r) for r in table[:4])
        periods = re.findall(r'Q([1-4])FY(\d{2,4})', re.sub(r'\s+', '', header))
        expected = [(str(quarter), str(fiscal_year)[-2:]), (str(quarter), str(fiscal_year - 1)[-2:])]
        normalized = [(q, y[-2:]) for q, y in periods]
        if not normalized or normalized[0] != expected[0] or expected[1] not in normalized:
            raise ValueError('Quarter / year comparison columns do not match')
        previous_index = normalized.index(expected[1])
        revenue = labelled(table, ('revenue',)); income = labelled(table, ('net income', 'net income (loss)'))
        eps = labelled(table, ('diluted earnings per share', 'earnings per share', 'gaap earnings per diluted share'))
        # Guidance is numeric management outlook, not analyst expectations or text sentiment.
        outlook = re.search(r'(?:outlook for|outlook is)', snippet, re.I)
        if outlook:
            g = re.search(r'Revenue is expected to be (?:approximately )?\$([\d.]+)\s*(billion|million)', snippet[outlook.start():], re.I)
            if g: guidance = float(g[1]) * (1000 if g[2].lower() == 'billion' else 1)
    elif symbol == 'MSFT':
        if not re.search(r'(?:FY\s*' + str(fiscal_year)[-2:] + r'\s*Q' + str(quarter) + ')', text, re.I):
            raise ValueError('Microsoft release identity mismatch')
        start = text.find('REDMOND')
        if start < 0: raise ValueError('Microsoft original press release missing')
        snippet = text[start:start + 5000]
        published = re.search(DATE, snippet)
        ended = re.search(r'quarter ended\s+(' + DATE + ')', snippet, re.I)
        table = next((t for t in doc.tables if any('Three Months Ended' in ' '.join(r) for r in t[:12])
                      and any(r and re.sub(r'\s+', ' ', r[0]).lower().strip() in ('total revenue', 'revenue') and len(numbers(r)) >= 2 for r in t)
                      and any(r and r[0].strip().lower() == 'diluted' for r in t)), None)
        if table is None: raise ValueError('Missing Microsoft quarterly income statement')
        revenue = labelled(table, ('total revenue', 'revenue')); income = labelled(table, ('net income', 'net income (loss)', 'net loss'))
        eps = labelled(table, ('diluted',)); previous_index = 1
    else: raise ValueError('Unsupported issuer')
    if not published or not ended: raise ValueError('Release or fiscal-period date missing')
    publication = iso(published[0]); period_end = iso(ended[1])
    expected_month = ((quarter*3 + (0 if symbol == 'NVDA' else 5)) % 12) + 1
    expected_year = fiscal_year - int((symbol == 'NVDA' and quarter < 4) or (symbol == 'MSFT' and quarter < 3))
    expected_end = date(expected_year,expected_month,calendar.monthrange(expected_year,expected_month)[1])
    if abs((date.fromisoformat(period_end)-expected_end).days) > (10 if symbol == 'NVDA' else 0):
        raise ValueError('Release fiscal period does not match requested quarter')
    if symbol == 'MSFT':
        years = re.findall(r'\b20\d{2}\b', ' '.join(' '.join(r) for r in table[:12]))
        if len(years) < 2 or years[:2] != [str(expected_year),str(expected_year-1)]:
            raise ValueError('Microsoft current / prior year column order mismatch')
    if not 0 <= (date.fromisoformat(publication) - date.fromisoformat(period_end)).days <= 100:
        raise ValueError('Implausible publication lag')
    if min(len(revenue), len(income), len(eps)) <= previous_index or revenue[0] <= 0 or revenue[previous_index] <= 0:
        raise ValueError('Incomplete comparable financial columns')
    # Both EPS values come from the SAME release, so stock-split bases match.
    prior_eps = eps[previous_index]
    return dict(symbol=symbol, fiscalYear=fiscal_year, quarter=quarter, availableDate=publication,
                periodEnd=period_end, periodType='quarter', basis='GAAP', currency='USD', unit='millions except EPS',
                revenue=revenue[0], priorYearRevenue=revenue[previous_index], netIncome=income[0],
                dilutedEps=eps[0], priorYearDilutedEps=prior_eps, nextQuarterRevenue=guidance,
                quarterRevenueGrowth=revenue[0]/revenue[previous_index]-1,
                quarterNetMargin=income[0]/revenue[0],
                quarterEpsChange=(eps[0]-prior_eps)/abs(prior_eps) if abs(prior_eps) >= .01 else None,
                nextQuarterRevenueGrowth=guidance/revenue[0]-1 if guidance else None,
                source='Company original quarterly earnings release', sourceUrl=url,
                sourceSha256=hashlib.sha256(html.encode()).hexdigest(), parserVersion=PARSER_VERSION)


def earnings_before(rows, day):
    eligible = [r for r in rows if r['availableDate'] < day and
                0 <= (date.fromisoformat(day)-date.fromisoformat(r['periodEnd'])).days <= 200]
    if not eligible: return [float('nan')]*len(FIELDS), None
    latest = max(eligible, key=lambda r: (r['availableDate'], r['periodEnd']))
    return [float(latest[k]) if isinstance(latest.get(k), (int, float)) and math.isfinite(latest[k])
            else float('nan') for k in FIELDS], latest['availableDate']


def release_url(symbol, year, quarter):
    if symbol == 'MSFT': return f'https://www.microsoft.com/en-us/Investor/earnings/FY-{year}-Q{quarter}/press-release-webcast'
    word = ('first', 'second', 'third', 'fourth')[quarter-1]
    part = f'{word}-quarter-' + ('and-' if quarter == 4 else '') + f'fiscal-{year}'
    if (year,quarter)==(2015,2):return 'https://nvidianews.nvidia.com/news/nvidia-financial-results-for-' + part
    verb = 'reports' if year == 2014 else 'announces'
    return f'https://nvidianews.nvidia.com/news/nvidia-{verb}-financial-results-for-' + part


def snapshot_observations(root):
    """Only previously observed snapshots; they never become old financial releases."""
    target = root/'research/fundamental-observations.json'
    old = json.loads(target.read_text()) if target.exists() else dict(schemaVersion=1, observations=[])
    keys = {(r['symbol'], r['observedAt']) for r in old['observations']}
    source = root/'fundamentals/latest_fundamentals.csv'
    if source.exists():
        for row in csv.DictReader(source.read_text().splitlines()):
            key = (row.get('symbol'), row.get('updatedAt'))
            if not all(key) or key in keys: continue
            values = {}
            for field in ('forwardEps', 'trailingEps', 'revenueGrowth', 'earningsGrowth', 'profitMargins'):
                try:
                    value = float(row.get(field, ''))
                    if math.isfinite(value): values[field] = value
                except (ValueError, TypeError): pass
            if values:
                old['observations'].append(dict(symbol=key[0], observedAt=key[1], source='Yahoo fundamentals snapshot', **values))
                keys.add(key)
    atomic_json(target, old)


def build(root=ROOT, download=True, now=None):
    now = now or datetime.now(timezone.utc); today = now.date()
    path = root/'research/earnings.json'; old = json.loads(path.read_text()) if path.exists() else {}
    rows = old.get('issuers', {}); states = old.get('requestState', {}); errors = []
    cache = root/'research/source-cache/earnings'; cache.mkdir(parents=True, exist_ok=True)
    for symbol in ('NVDA', 'MSFT'):
        state = states.setdefault(symbol, {}); existing = {(r['fiscalYear'],r['quarter']):r for r in rows.get(symbol, [])}
        if download and state.get('blockedUntil', '') > now.isoformat():
            errors.append(f'{symbol}: provider backoff active until {state["blockedUntil"]}')
            continue
        for year in range(2014, today.year+2):
            for quarter in range(1, 5):
                # Do not request future quarters before their approximate fiscal period ends.
                month = ((quarter*3 + (0 if symbol == 'NVDA' else 5)) % 12) + 1
                cal_year = year - (1 if (symbol == 'NVDA' and quarter < 4) or (symbol == 'MSFT' and quarter < 3) else 0)
                expected_end = date(cal_year, month, calendar.monthrange(cal_year,month)[1])
                if expected_end > today or (year, quarter) in existing: continue
                key = f'{year}-Q{quarter}'; previous = state.get(key, {})
                if download and previous.get('nextCheck', '') > today.isoformat(): continue
                p = cache/f'{symbol}-{key}.html'; url = release_url(symbol, year, quarter)
                try:
                    if p.exists(): html = p.read_text()
                    elif not download: continue
                    else:
                        with urlopen(Request(url, headers={'User-Agent':'PublicForecastResearch/1.0 https://github.com/bumblev95/S-P-500-'}), timeout=25) as response:
                            if response.url.split('/')[2] != url.split('/')[2]: raise ValueError('Unexpected redirect host')
                            html = response.read().decode('utf-8')
                        time.sleep(.75)
                    row = parse_release(symbol, year, quarter, html, url)
                    if row['availableDate'] > today.isoformat(): raise ValueError('Future release cannot be imported')
                    if not p.exists(): p.write_text(html)
                    row['firstRetrievedAt'] = now.isoformat(); existing[(year, quarter)] = row
                    state.pop(key, None); print(symbol, key, row['availableDate'], 'GAAP imported', flush=True)
                except Exception as exc:
                    message = f'{symbol} {key}: {type(exc).__name__} {exc}'
                    delay = 1 if (today-expected_end).days <= 180 else 30
                    state[key] = dict(error=message, nextCheck=(today+timedelta(days=delay)).isoformat())
                    errors.append(message); print(message, flush=True)
                    if isinstance(exc, HTTPError) and exc.code in (401,403,429):
                        state['blockedUntil'] = (now+timedelta(days=1)).isoformat()
                        rows[symbol] = sorted(existing.values(), key=lambda r: (r['availableDate'], r['periodEnd']))
                        atomic_json(path, {**old, 'issuers':rows, 'requestState':states})
                        break
            else: continue
            break
        rows[symbol] = sorted(existing.values(), key=lambda r: (r['availableDate'],r['periodEnd']))
    coverage={}
    for symbol,values in rows.items():
        available={(r['fiscalYear'],r['quarter']) for r in values};missing=[]
        for year in range(2014,today.year+2):
            for q in range(1,5):
                month=((q*3+(0 if symbol=='NVDA' else 5))%12)+1
                cal_year=year-int((symbol=='NVDA' and q<4) or (symbol=='MSFT' and q<3))
                if date(cal_year,month,calendar.monthrange(cal_year,month)[1])<=today and (year,q) not in available:
                    missing.append(f'{year}-Q{q}')
        coverage[symbol]=dict(releases=len(values),firstDate=values[0]['availableDate'] if values else None,lastDate=values[-1]['availableDate'] if values else None,missingQuarters=missing)
    result = dict(schemaVersion=1, generatedAt=now.isoformat(), issuers=rows, requestState=states,
                  errors=errors, coverage=coverage,
                  limitations=['Free original-release pilot: NVDA and MSFT only, not the whole dashboard universe.',
                    'Original dated corporate pages reconstructed today are not a certified point-in-time feed.',
                    'Previously imported releases are immutable; current Yahoo snapshots are observation-only.',
                    'GAAP quarterly features; no analyst-consensus surprise or automated narrative interpretation.',
                    'Management revenue guidance is included only when explicitly present; missing is not zero.',
                    'Usable after the publication date; maximum fiscal-period age is 200 days.'])
    atomic_json(path, result); snapshot_observations(root)
    return result


if __name__ == '__main__':
    import sys
    build(download='--offline' not in sys.argv)
