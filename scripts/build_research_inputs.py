"""Public, publication-dated covariates. Never backfill a current snapshot into history."""
import json, math, os, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit
from build_forecasts import atomic_json

ROOT = Path(__file__).resolve().parents[1]
CIKS = dict(NVDA=1045810, AMD=2488, AVGO=1730168, MU=723125, AMAT=6951,
            QCOM=804328, INTC=50863, MSFT=789019, AAPL=320193, GOOGL=1652044,
            AMZN=1018724, META=1326801, TSLA=1318605, JPM=19617, XOM=34088)
TAGS = dict(revenue=['RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet', 'Revenues'],
            income=['NetIncomeLoss'], cashflow=['NetCashProvidedByUsedInOperatingActivities'],
            assets=['Assets'], liabilities=['Liabilities'])
STOCK_FIELDS = ['revenueGrowth', 'netMargin', 'cashflowMargin', 'liabilitiesToAssets']
CRYPTO_FIELDS = ['funding7d', 'funding30d', 'oiChange7d', 'supplyChange30d']
HL = 'https://api.hyperliquid.xyz/info'

def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)

def extract_facts(payload):
    result = []
    for name, tags in TAGS.items():
        for rank, tag in enumerate(tags):
            for r in payload.get('facts', {}).get('us-gaap', {}).get(tag, {}).get('units', {}).get('USD', []):
                if r.get('form') not in ('10-K', '10-Q', '10-K/A', '10-Q/A') or not finite(r.get('val')): continue
                try:
                    filed = datetime.fromisoformat(r['filed']); end = datetime.fromisoformat(r['end'])
                    if end > filed: continue
                    if name in ('revenue', 'income', 'cashflow'):
                        duration = (end - datetime.fromisoformat(r['start'])).days
                        if not 330 <= duration <= 400: continue  # comparable annual periods; no YTD/quarter mixing
                except (KeyError, ValueError, TypeError): continue
                result.append(dict(name=name, tag=tag, rank=rank, filed=r['filed'], end=r['end'],
                                   start=r.get('start'), value=r['val'], accession=r.get('accn')))
    return result

def annual_snapshot(facts, filed):
    available = [r for r in facts if r['filed'] <= filed]
    revenues = [r for r in available if r['name'] == 'revenue' and r['value'] > 0]
    if not revenues: return None
    end = max(r['end'] for r in revenues)
    rev = sorted([r for r in revenues if r['end'] == end], key=lambda r: (r['rank'], -datetime.fromisoformat(r['filed']).timestamp(), r['accession'] or ''))[0]
    used = [rev]
    def matching(name):
        values = [r for r in available if r['name'] == name and r['end'] == end and
                  (name in ('assets', 'liabilities') or r['start'] == rev['start'])]
        if not values: return None
        r = max(values, key=lambda r: (r['filed'], r['accession'] or '')); used.append(r)
        return r['value']
    prior = [r for r in revenues if r['tag'] == rev['tag'] and 330 <=
             (datetime.fromisoformat(end)-datetime.fromisoformat(r['end'])).days <= 400 and
             abs((datetime.fromisoformat(rev['start'])-datetime.fromisoformat(r['start'])).days -
                 (datetime.fromisoformat(end)-datetime.fromisoformat(r['end'])).days) <= 7]
    previous = max(prior, key=lambda r: (r['end'], r['filed'], r['accession'] or '')) if prior else None
    if previous: used.append(previous)
    income, cashflow, assets, liabilities = (matching(k) for k in ('income', 'cashflow', 'assets', 'liabilities'))
    return dict(availableDate=filed, periodEnd=end,
                revenueGrowth=rev['value']/previous['value']-1 if previous else None,
                netMargin=income/rev['value'] if income is not None else None,
                cashflowMargin=cashflow/rev['value'] if cashflow is not None else None,
                liabilitiesToAssets=liabilities/assets if liabilities is not None and assets and assets > 0 else None,
                evidence=[dict(tag=r['tag'], filed=r['filed'], periodEnd=r['end'], accession=r['accession']) for r in used])

def financial_history(payload):
    facts = extract_facts(payload)
    return [s for d in sorted({r['filed'] for r in facts}) if (s := annual_snapshot(facts, d))]

def stock_before(rows, day):
    # Filed date has no reliable intraday timestamp: usable only on a later date.
    eligible = [r for r in rows if r['availableDate'] < day and
                0 <= (datetime.fromisoformat(day)-datetime.fromisoformat(r['periodEnd'])).days <= 550]
    if not eligible: return [float('nan')]*4, None
    r = eligible[-1]
    return [float(r[k]) if finite(r.get(k)) else float('nan') for k in STOCK_FIELDS], r['availableDate']

def daily_funding(raw):
    by = {}
    for r in raw:
        day = datetime.fromtimestamp(r['time']/1000, timezone.utc).date().isoformat()
        by.setdefault(day, {})[r['time']] = float(r['fundingRate'])
    # Only complete hourly days; missing hours are not zero funding.
    return [dict(date=d, rate=sum(values.values()), hours=len(values)) for d, values in sorted(by.items()) if len(values) == 24]

def crypto_before(funding, snapshots, day):
    now = datetime.fromisoformat(day)
    def rate(days):
        rows = [r for r in funding if 0 < (now-datetime.fromisoformat(r['date'])).days <= days]
        return sum(r['rate'] for r in rows) if len(rows) == days else float('nan')
    def change(key, days):
        values = [r for r in snapshots if r['date'] < day and finite(r.get(key)) and r[key] > 0]
        if not values: return float('nan')
        last = values[-1]
        if (now-datetime.fromisoformat(last['date'])).days > 3: return float('nan')
        previous = [r for r in values if days <= (datetime.fromisoformat(last['date'])-datetime.fromisoformat(r['date'])).days <= days+2]
        return last[key]/previous[-1][key]-1 if previous else float('nan')
    x = [rate(7), rate(30), change('openInterest', 7), change('circulating', 30)]
    used = [r['date'] for r in funding if r['date'] < day and (now-datetime.fromisoformat(r['date'])).days <= 30]
    used += [r['date'] for r in snapshots if r['date'] < day and (now-datetime.fromisoformat(r['date'])).days <= 35]
    return x, max(used) if any(math.isfinite(v) for v in x) and used else None

def sec_identity():
    identity=os.environ.get('SEC_USER_AGENT','').strip()
    if '\n' in identity or '\r' in identity or not re.search(r'\S+@[^\s@]+\.[^\s@]+',identity):
        raise ValueError('SEC contact configuration missing: set SEC_USER_AGENT to an app name and a real contact email')
    return identity

def request(url, body=None):
    # The SEC contact is sent only to SEC, never to the crypto provider.
    identity=sec_identity() if urlsplit(url).hostname in ('data.sec.gov','www.sec.gov') else 'PublicForecastResearch/1.0 https://github.com/bumblev95/S-P-500-'
    headers = {'User-Agent': identity, 'Content-Type': 'application/json'}
    with urlopen(Request(url, data=json.dumps(body).encode() if body else None, headers=headers), timeout=25) as r:
        return json.load(r)

def funding_page(symbol,start,end):
    batch=request(HL,dict(type='fundingHistory',coin=symbol,startTime=start,endTime=end))
    if not isinstance(batch,list):raise ValueError('Invalid funding response')
    # Official weight: 20 plus one per 20 returned records; stay below 1000/min.
    time.sleep((20+math.ceil(len(batch)/20))*60/1000)
    return [r for r in batch if r.get('coin')==symbol and start<=r.get('time',0)<=end]

def build(root=ROOT, download=True):
    path = root/'research/inputs.json'; old = json.loads(path.read_text()) if path.exists() else {}
    cache = root/'research/source-cache'; cache.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc); today = now.date().isoformat()
    stocks = old.get('stocks', {}); funding = old.get('funding', {}); snapshots = old.get('snapshots', {}); errors = []
    blocked_until=old.get('secBlockedUntil','')
    if not blocked_until and any(e.startswith('SEC ') and any(str(code) in e for code in (401,403,429)) for e in old.get('errors',[])):
        blocked_until=(datetime.fromisoformat(old['generatedAt'])+timedelta(days=1)).isoformat()
    halted = not download or blocked_until>now.isoformat()
    if download and blocked_until>now.isoformat():errors.extend(e for e in old.get('errors',[]) if e.startswith('SEC '))
    if download:
        try:sec_identity()
        except ValueError as e:halted=True;errors.append(str(e))
    for symbol, cik in CIKS.items():
        p = cache/(symbol+'.json')
        try:
            if not halted:
                payload = request(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
                if int(payload.get('cik', -1)) != cik: raise ValueError('SEC issuer identity mismatch')
                atomic_json(p, payload); time.sleep(.2)
            elif p.exists(): payload = json.loads(p.read_text())
            else: continue
            if int(payload.get('cik',-1))!=cik:raise ValueError('Cached SEC issuer identity mismatch')
            stocks[symbol] = dict(stocks.get(symbol,{}),cik=cik, source='SEC companyfacts / annual US-GAAP', rows=financial_history(payload), retrievedAt=now.isoformat() if not halted else stocks.get(symbol, {}).get('retrievedAt'))
        except Exception as e:
            errors.append(f'SEC {symbol}: {e}')
            if isinstance(e, HTTPError) and e.code in (401, 403, 429):
                halted = True;blocked_until=(now+timedelta(days=1)).isoformat()
    market = json.loads((root/'crypto/latest.json').read_text())
    # Preserve first observed value per day, never rewrite past supply/OI with today's snapshot.
    for symbol in market['coins']:
        existing = {r['date']: r for r in snapshots.get(symbol, [])}
        observations = json.loads((root/'crypto/observations.json').read_text())
        for r in observations:
            if r.get('symbol') != symbol: continue
            d = r['at'][:10]
            if d not in existing:
                existing[d] = dict(date=d, observedAt=r['at'], circulating=r.get('circulating'), openInterest=r.get('openInterest'))
        snapshots[symbol] = [existing[d] for d in sorted(existing)]
    halted = not download
    backfill=old.get('fundingBackfill',{})
    for symbol, coin in market['coins'].items():
        if not coin.get('perp') or halted: continue
        p = cache/('funding-'+symbol+'.json')
        raw = json.loads(p.read_text()) if p.exists() else []
        start = max([r['time'] for r in raw], default=int((now-timedelta(days=90)).timestamp()*1000)) + 1
        try:
            for _ in range(8):  # bounded paging; resume next run if provider truncates
                batch = funding_page(symbol,start,int(now.timestamp()*1000))
                if not batch: break
                raw.extend(batch); start = max(r['time'] for r in batch)+1;atomic_json(p,raw)
            if symbol in ('BTC','ETH','SOL'):
                progress=cache/('funding-backfill-'+symbol+'.json')
                state=json.loads(progress.read_text()) if progress.exists() else backfill.get(symbol)
                if state is None:state=dict(cursor=int((now-timedelta(days=1095)).timestamp()*1000),end=min([r['time'] for r in raw],default=int(now.timestamp()*1000))-1,completed=False)
                backfill[symbol]=state
                for _ in range(64):
                    if state['completed']:break
                    batch=funding_page(symbol,state['cursor'],state['end'])
                    if not batch:state['completed']=True;break
                    raw.extend(batch);state['cursor']=max(r['time'] for r in batch)+1
                    if state['cursor']>state['end']:state['completed']=True
                    atomic_json(p,raw)
                    # Persist paging progress even if a later request is denied.
                    atomic_json(progress,state)
            raw = list({r['time']: r for r in raw}.values()); atomic_json(p, raw)
            # Combine previously published complete days even after a cache eviction.
            days = {r['date']: r for r in funding.get(symbol, [])}
            days.update({r['date']: r for r in daily_funding(raw) if r['date'] < today})
            funding[symbol] = [days[d] for d in sorted(days)]
        except Exception as e:
            errors.append(f'Hyperliquid {symbol}: {e}')
            if isinstance(e, HTTPError) and e.code in (401, 403, 429): halted = True
            days={r['date']:r for r in funding.get(symbol,[])}
            days.update({r['date']:r for r in daily_funding(raw) if r['date']<today});funding[symbol]=[days[d] for d in sorted(days)]
    result = dict(schemaVersion=1, generatedAt=now.isoformat(), secBlockedUntil=blocked_until, stocks=stocks, funding=funding, fundingBackfill=backfill, snapshots=snapshots, errors=errors,
                  limitations=['SEC original filed dates, standard annual USD facts only; not a certified vintage feed.', 'No guidance, earnings surprises, news or unlock forecasts.', 'Hyperliquid funding is exchange-specific; OI and supply begin when observed here.', 'Current snapshots are never copied into old backtests.'])
    atomic_json(path, result)
    print('Research inputs:', len(stocks), 'SEC issuers;', len(funding), 'funding series;', errors, flush=True)
    return result

if __name__ == '__main__':
    import sys
    build(download='--offline' not in sys.argv)
