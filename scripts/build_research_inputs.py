"""Public, publication-dated covariates. Never backfill a current snapshot into history."""
import json, math, os, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit
from build_forecasts import atomic_json
from research_universe import targets
from sec_fallbacks import (PARSER_VERSION, POLICY_HASH, PREDECESSORS, parse_cik,
                          expand_facts, attach_predecessor, evidence_for, diagnostics,
                          payload_hash)

ROOT = Path(__file__).resolve().parents[1]
CIKS = dict(NVDA=1045810, AMD=2488, AVGO=1730168, MU=723125, AMAT=6951,
            QCOM=804328, INTC=50863, MSFT=789019, AAPL=320193, GOOGL=1652044,
            AMZN=1018724, META=1326801, TSLA=1318605, JPM=19617, XOM=34088)
TAGS = dict(revenue=['RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet', 'Revenues', 'RevenuesNetOfInterestExpense', 'RealEstateRevenueNet'],
            income=['NetIncomeLoss'], cashflow=['NetCashProvidedByUsedInOperatingActivities'],
            assets=['Assets'], liabilities=['Liabilities'])
STOCK_FIELDS = ['revenueGrowth', 'netMargin', 'cashflowMargin', 'liabilitiesToAssets']
CRYPTO_FIELDS = ['funding7d', 'funding30d', 'oiChange7d', 'supplyChange30d']
HL = 'https://api.hyperliquid.xyz/info'

def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)

def extract_facts(payload):
    result = []
    try: cik = parse_cik(payload.get('cik'))
    except ValueError: cik = None
    for name, tags in TAGS.items():
        for rank, tag in enumerate(tags):
            for r in payload.get('facts', {}).get('us-gaap', {}).get(tag, {}).get('units', {}).get('USD', []):
                if r.get('form') not in ('10-K', '10-Q', '10-K/A', '10-Q/A') or isinstance(r.get('val'), bool) or not finite(r.get('val')): continue
                try:
                    filed = datetime.fromisoformat(r['filed']); end = datetime.fromisoformat(r['end'])
                    if end > filed: continue
                    if name in ('revenue', 'income', 'cashflow'):
                        duration = (end - datetime.fromisoformat(r['start'])).days
                        if not 330 <= duration <= 400: continue  # comparable annual periods; no YTD/quarter mixing
                except (KeyError, ValueError, TypeError): continue
                result.append(dict(name=name, tag=tag, rank=rank, filed=r['filed'], end=r['end'],
                                   start=r.get('start'), value=r['val'], accession=r.get('accn'),
                                   sourceCIK=cik, form=r['form']))
    return expand_facts(payload, result, len(TAGS['revenue']))

def annual_snapshot(facts, filed):
    available = [r for r in facts if r.get('knownDate', r['filed']) <= filed]
    revenues = [r for r in available if r['name'] == 'revenue' and r['value'] > 0]
    if not revenues: return None
    end = max(r['end'] for r in revenues)
    rev = sorted([r for r in revenues if r['end'] == end], key=lambda r: (r['rank'], -datetime.fromisoformat(r['filed']).timestamp(), r['accession'] or ''))[0]
    used = [rev]
    def matching(name):
        values = [r for r in available if r['name'] == name and r['end'] == end and r.get('sourceCIK') == rev.get('sourceCIK') and
                  (name in ('assets', 'liabilities') or r['start'] == rev['start'])]
        if not values: return None
        r = max(values, key=lambda r: (r['filed'], r['accession'] or '')); used.append(r)
        return r['value']
    prior = [r for r in revenues if r['tag'] == rev['tag'] and r.get('sourceCIK') == rev.get('sourceCIK') and 330 <=
             (datetime.fromisoformat(end)-datetime.fromisoformat(r['end'])).days <= 400 and
             abs((datetime.fromisoformat(rev['start'])-datetime.fromisoformat(r['start'])).days -
                 (datetime.fromisoformat(end)-datetime.fromisoformat(r['end'])).days) <= 7]
    previous = max(prior, key=lambda r: (r['end'], r['filed'], r['accession'] or '')) if prior else None
    if previous: used.append(previous)
    income, cashflow, assets, liabilities = (matching(k) for k in ('income', 'cashflow', 'assets', 'liabilities'))
    snapshot = dict(availableDate=filed, periodEnd=end,
                revenueGrowth=rev['value']/previous['value']-1 if previous else None,
                netMargin=income/rev['value'] if income is not None else None,
                cashflowMargin=cashflow/rev['value'] if cashflow is not None else None,
                liabilitiesToAssets=liabilities/assets if liabilities is not None and assets and assets > 0 else None,
                evidence=[e for r in used for e in evidence_for(r, bool(rev.get('fallback')))])
    if rev.get('fallback'):
        snapshot.update(fallbacks=sorted({r['fallback'] for r in used if r.get('fallback')}),
                        revenueBasis=rev['tag'], sourceCIK=rev.get('sourceCIK'))
        if rev.get('mapping'): snapshot['mappingEvidence'] = rev['mapping']
    return snapshot

def financial_history(payload, predecessor=None, as_of=None):
    facts = extract_facts(payload)
    if predecessor is not None: attach_predecessor(payload, predecessor, facts, extract_facts)
    if as_of is not None: facts = [r for r in facts if r.get('knownDate', r['filed']) <= as_of]
    return [s for d in sorted({r.get('knownDate', r['filed']) for r in facts}) if (s := annual_snapshot(facts, d))]

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

def sec_coverage(wanted, stocks, status, diagnostic, requests=0):
    groups = {}
    for symbol, cik in wanted.items(): groups.setdefault(cik, []).append(symbol)
    usable = {c for c, syms in groups.items() if any(stocks.get(s, {}).get('cik') == c and stocks[s].get('rows') for s in syms)}
    fallback = {c for c, syms in groups.items() if c in usable and any(
        row.get('fallbacks') for s in syms if stocks.get(s, {}).get('cik') == c
        for row in stocks.get(s, {}).get('rows', []))}
    missing = [s for s, c in wanted.items() if stocks.get(s, {}).get('cik') != c or not stocks[s].get('rows')]
    return dict(targetTickers=len(wanted), targetIssuers=len(groups), usableIssuers=len(usable),
                usableTickers=len(wanted)-len(missing), fallbackIssuers=len(fallback),
                requests=requests, status=status, missingSymbols=missing, diagnostics=diagnostic,
                parserVersion=PARSER_VERSION, fallbackPolicyHash=POLICY_HASH)


def collect_sec(old, root, download, now):
    """One current request per issuer; only reviewed predecessors can add a request."""
    cache=root/'research/source-cache';cache.mkdir(parents=True,exist_ok=True)
    wanted=targets(root,CIKS);groups={}
    for symbol,cik in wanted.items(): groups.setdefault(cik,[]).append(symbol)
    stocks=dict(old.get('stocks',{}));errors=[];status={}
    diagnostic={k:v for k,v in old.get('secCoverage',{}).get('diagnostics',{}).items() if int(k) in groups}
    blocked=old.get('secBlockedUntil','')
    if not blocked and any(e.startswith('SEC ') and any(str(code) in e for code in (401,403,429)) for e in old.get('errors',[])):
        blocked=(datetime.fromisoformat(old['generatedAt'])+timedelta(days=1)).isoformat()
    halted=not download or bool(blocked and datetime.fromisoformat(blocked)>now)
    configured=None
    if download:
        try:sec_identity();configured=True
        except ValueError as exc:halted=True;configured=False;errors.append(str(exc))
    if blocked and datetime.fromisoformat(blocked)>now:
        errors.extend(e for e in old.get('errors',[]) if e.startswith('SEC '))
    print('SEC contact configured:',configured,'; request backoff active:',bool(blocked and datetime.fromisoformat(blocked)>now),flush=True)
    requests=0
    def checkpoint():
        coverage=sec_coverage(wanted,stocks,status,diagnostic,requests)
        out={**old,'schemaVersion':1,'generatedAt':now.isoformat(),'stocks':stocks,'errors':errors,
             'secBlockedUntil':blocked,'secContactConfigured':configured,'secCoverage':coverage}
        atomic_json(root/'research/inputs.json',out)
        return out
    def deny(exc):
        nonlocal halted,blocked
        if isinstance(exc,HTTPError) and exc.code in (401,403,429):
            halted=True;blocked=(now+timedelta(days=1)).isoformat();checkpoint()
    def cached(path,cik):
        if not path.exists(): return None
        payload=json.loads(path.read_text())
        if parse_cik(payload.get('cik'))!=cik: raise ValueError('Cached SEC issuer identity mismatch')
        return payload
    def fetch(cik,path):
        nonlocal requests
        requests+=1
        try:
            payload=request(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
            if parse_cik(payload.get('cik'))!=cik: raise ValueError('SEC issuer identity mismatch')
            # Compute before caching: malformed/nonfinite JSON isn't a usable source.
            payload_hash(payload);atomic_json(path,payload)
            return payload
        finally: time.sleep(.5)
    for i,(cik,symbols) in enumerate(groups.items()):
        symbol=symbols[0]
        previous=next((stocks[s] for s in symbols if stocks.get(s,{}).get('cik')==cik), {})
        if not previous:
            previous=next((v for v in stocks.values() if v.get('cik')==cik), {})
        fresh=False
        try: fresh=bool(previous and timedelta(0)<=now-datetime.fromisoformat(previous.get('retrievedAt'))<timedelta(hours=20))
        except (TypeError,ValueError): pass
        if fresh and previous.get('parserVersion')==PARSER_VERSION and previous.get('fallbackPolicyHash')==POLICY_HASH:
            for s in symbols:stocks[s]=dict(previous)
            status[str(cik)]='fresh' if previous.get('rows') else 'no_standard_annual_facts'
            continue
        source_path=cache/(symbol+'.json')
        payload=None;predecessor=None;observed=previous.get('retrievedAt');mode='cache_reprocessed'
        try:
            # Parser updates can reprocess a fresh cached source during backoff.
            # Cache absence alone isn't proof of missing facts.
            if fresh or halted: payload=cached(source_path,cik)
            if payload is None and fresh and previous.get('rows') and cik not in PREDECESSORS:
                for s in symbols: stocks[s]=dict(previous)
                status[str(cik)]='fresh'
                diagnostic.setdefault(str(cik),dict(state='not_reparsed',reason='raw_source_unavailable'))
                continue
            if payload is None and not halted:
                payload=fetch(cik,source_path);observed=now.isoformat();mode='updated'
            if payload is None:
                status[str(cik)]='retained' if previous.get('rows') else 'deferred'
                diagnostic.setdefault(str(cik),dict(state='not_reparsed',reason='raw_source_unavailable'))
                continue
            policy=PREDECESSORS.get(cik)
            resolver_error=None
            if policy and now.date().isoformat()>=max(policy['filed'],policy['effectiveDate']):
                try:
                    p=cache/f"CIK{policy['sourceCIK']:010d}.json"
                    predecessor=cached(p,policy['sourceCIK'])
                    if predecessor is None and not halted: predecessor=fetch(policy['sourceCIK'],p)
                except Exception as exc:
                    resolver_error=str(exc);errors.append(f'SEC {symbol} predecessor: {exc}');deny(exc)
            rows=financial_history(payload,predecessor,as_of=now.date().isoformat())
            detail=diagnostics(payload,rows,TAGS['revenue'],predecessor)
            if policy:
                detail['predecessorState']='available' if predecessor is not None else ('error' if resolver_error else 'unavailable_or_not_yet_effective')
                if resolver_error: detail['predecessorError']=resolver_error
            diagnostic[str(cik)]={**detail,'processedAt':now.isoformat(),'collectionMode':mode}
            if not rows and previous.get('rows'):
                for s in symbols: stocks[s]=dict(previous)
                status[str(cik)]='retained_no_usable_refresh'
                diagnostic[str(cik)]['retainedPreviousHistory']=True
                continue
            result=dict(cik=cik,source='SEC companyfacts / annual US-GAAP',rows=rows,retrievedAt=observed,
                        parserVersion=PARSER_VERSION,fallbackPolicyHash=POLICY_HASH,
                        sourcePayloadHashes=detail['sourcePayloadHashes'])
            for s in symbols:stocks[s]=dict(result)
            status[str(cik)]=mode if rows else 'no_standard_annual_facts'
        except Exception as exc:
            errors.append(f'SEC {symbol}: {exc}');status[str(cik)]='error'
            diagnostic[str(cik)]=dict(state='error',reason='source_unverified',error=str(exc))
            deny(exc)
        if (i+1)%25==0:
            checkpoint();print('SEC progress:',i+1,'/',len(groups),'issuers;',requests,'requests',flush=True)
    return checkpoint()

def build(root=ROOT, download=True, stocks_only=False):
    path = root/'research/inputs.json'; old = json.loads(path.read_text()) if path.exists() else {}
    cache = root/'research/source-cache'; cache.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc); today = now.date().isoformat()
    collected=collect_sec(old,root,download,now)
    stocks=collected['stocks'];funding=old.get('funding',{});snapshots=old.get('snapshots',{});errors=collected['errors']
    if stocks_only:
        print('Research inputs:',collected['secCoverage']['usableIssuers'],'SEC issuers;',errors,flush=True)
        return collected
    blocked_until=collected['secBlockedUntil'];sec_configured=collected['secContactConfigured']
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
    result = dict(schemaVersion=1, secCoverage=collected['secCoverage'], generatedAt=now.isoformat(), secBlockedUntil=blocked_until, secContactConfigured=sec_configured, stocks=stocks, funding=funding, fundingBackfill=backfill, snapshots=snapshots, errors=errors,
                  limitations=['SEC original filed dates, standard annual USD facts only; not a certified vintage feed.', 'No guidance, earnings surprises, news or unlock forecasts.', 'Hyperliquid funding is exchange-specific; OI and supply begin when observed here.', 'Current snapshots are never copied into old backtests.'])
    atomic_json(path, result)
    print('Research inputs:', collected['secCoverage']['usableIssuers'], 'SEC issuers;', len(funding), 'funding series;', errors, flush=True)
    return result

if __name__ == '__main__':
    import sys
    build(download='--offline' not in sys.argv,stocks_only='--stocks-only' in sys.argv)
