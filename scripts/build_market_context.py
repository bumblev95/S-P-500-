"""Public-source early warnings. Thresholds are heuristics, never probabilities.

No ICE index values are downloaded or redistributed. Missing observations are
not zero. This snapshot is not a point-in-time dataset for historical backtests.
"""
import csv
import io
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
# id: label, unit, observation-age limit, warning levels, change warning, source
SERIES = {
    'DGS10': ('미국 10년 국채 금리', '%', 7, None, None, 'Federal Reserve Board'),
    'DTWEXBGS': ('광의 달러 지수', 'index', 10, None, None, 'Federal Reserve Board'),
    'NFCI': ('금융여건', 'index', 16, [0, .5, 1], .25, 'Federal Reserve Bank of Chicago'),
    'STLFSI4': ('금융 스트레스', 'index', 16, [0, 1, 2], .5, 'Federal Reserve Bank of St. Louis'),
    'DRTSCILM': ('은행 기업대출 긴축', '%', 150, [10, 25, 50], 10, 'Board of Governors of the Federal Reserve System'),
    'SOFR': ('SOFR', '%', 5, None, None, 'Federal Reserve Bank of New York'),
    'IORB': ('IORB', '%', 5, None, None, 'Board of Governors of the Federal Reserve System'),
}
EBP_URL = 'https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv'
EBP_NOTE = 'https://www.federalreserve.gov/econres/notes/feds-notes/updating-the-recession-risk-and-the-excess-bond-premium-20161006.html'

def bond_spreads(text, today):
    """Fed research bond spread, monthly; EBP is a component, not total spread."""
    values = {'gz_spread': [], 'ebp': []}
    for raw in csv.DictReader(io.StringIO(text)):
        row = {k.strip().lower(): v for k, v in raw.items() if k}
        raw_date = row.get('date', '').strip()
        try:
            d = date.fromisoformat(raw_date[:10] if len(raw_date) >= 10 else raw_date+'-01')
        except ValueError:
            try: d = datetime.strptime(raw_date, '%m/%d/%Y').date()
            except ValueError: continue
        if not 0 <= (today-d).days < 900: continue
        for key in values:
            try:
                v = float(row[key])
                if math.isfinite(v): values[key].append((d.isoformat(), v))
            except (ValueError, KeyError, TypeError): pass
    out = []
    for key, label, limits, delta in [('gz_spread','회사채 GZ 신용스프레드',[2,3,4],.5), ('ebp','초과 채권 프리미엄 EBP',[0,.5,1],.25)]:
        rows = sorted(dict(values[key]).items())
        q = dict(id=key.upper(), label=label, source='Federal Reserve Board · staff research', url=EBP_NOTE, unit='%p', maxAgeDays=75, frequency='monthly', status='missing', value=None, asOf=None, severity=None)
        if rows:
            d,v = rows[-1]; prior=rows[-2] if len(rows)>1 else None; change=v-prior[1] if prior else None
            q.update(asOf=d, value=v, previousDate=prior[0] if prior else None, change=change, status='ready' if age(d,today)<=75 else 'stale', severity=max(sum(v>=x for x in limits), 1 if change is not None and change>=delta else 0))
        out.append(q)
    return out
FEEDS = [('Fed 발표', 'https://www.federalreserve.gov/feeds/press_all.xml'),
         ('Fed 연설', 'https://www.federalreserve.gov/feeds/speeches.xml')]
TOPICS = [
    ('자금조달·신용', r'liquidity|funding|private credit|nonbank|financial stability|repo market', '자금조달·차환 비용에 영향을 줄 수 있어 원문 확인이 필요합니다.'),
    ('은행·대출', r'banking|bank capital|loan|lending|credit conditions', '은행 대출 여건과 차입 의존 기업에 대한 영향을 확인하세요.'),
    ('금리·물가', r'fomc|monetary policy|interest rate|inflation|economic outlook', '정책 변화는 할인율과 성장주 가격 변동에 영향을 줄 수 있습니다.'),
]

def get(url):
    with urlopen(Request(url, headers={'User-Agent': 'PublicMarketMonitor/1.0'}), timeout=30) as r:
        return r.read(3_000_000).decode('utf-8-sig')

def age(d, today):
    try:
        return (today-date.fromisoformat(d[:10])).days
    except (ValueError, TypeError):
        return 9999

def parse_csv(text, key, today):
    rows = {}
    for row in csv.DictReader(io.StringIO(text)):
        d = row.get('observation_date') or row.get('DATE', '')
        try:
            v = float(row[key])
            if math.isfinite(v) and 0 <= age(d, today) < 900:
                rows[d] = v
        except (ValueError, KeyError, TypeError):
            pass
    return sorted(rows.items())

def parse_table(text, today):
    """FRED's data table has initial HTML rows and a deferred #date|value block."""
    pairs = re.findall(r'<th[^>]*scope="row"[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</th>\s*<td[^>]*>\s*([^<]+)</td>', text)
    pairs += re.findall(r'#(\d{4}-\d{2}-\d{2})\|\s*([^\s<]+)', text)
    rows = {}
    for d, value in pairs:
        try:
            v = float(value)
            if math.isfinite(v) and 0 <= age(d, today) < 900: rows[d] = v
        except (ValueError, TypeError): pass
    return sorted(rows.items())

def collect_series(key, today, fetcher):
    start = (today-timedelta(days=730)).isoformat()
    urls = [('csv', 'https://fred.stlouisfed.org/graph/fredgraph.csv?id='+key+'&cosd='+start),
            ('table', 'https://fred.stlouisfed.org/data/'+key+'.txt')]
    attempts = []
    for format_, url in urls:
        try:
            text = fetcher(url)
            rows = parse_csv(text, key, today) if format_ == 'csv' else parse_table(text, today)
            if not rows: raise ValueError('No valid observations')
            return rows, dict(fetchStatus='ready', dataUrl=url, fetchWarnings=attempts)
        except Exception as exc:
            attempts.append(format_+': '+(str(exc.code) if isinstance(exc, HTTPError) else type(exc).__name__))
            # No repeated requests following an explicit access/rate-limit rejection.
            if isinstance(exc, HTTPError) and exc.code in (403, 429): break
    return [], dict(fetchStatus='unavailable', fetchError='; '.join(attempts))

def retain_observation(entry, prior, today, error, now):
    """Keep a real last observation, its date and last successful fetch time."""
    if prior and isinstance(prior.get('value'), (int, float)) and math.isfinite(prior['value']):
        entry = dict(prior, status='ready' if 0 <= age(prior.get('asOf'), today) <= entry['maxAgeDays'] else 'stale')
        # Older snapshots discarded severity after one failed fetch. Recompute it.
        if entry['id'] in SERIES:
            _, _, _, limits, delta, _ = SERIES[entry['id']]
            severity = sum(entry['value'] >= x for x in limits) if limits else None
            if severity is not None and delta and entry.get('change') is not None and entry['change'] >= delta:
                severity = max(1, severity)
            entry['severity'] = severity
        entry['fromCache'] = True
    else:
        entry = dict(entry, status='missing', fromCache=False)
    entry.update(fetchStatus='unavailable', fetchError=error, lastAttemptAt=now.isoformat())
    return entry

def summarize(key, rows, today):
    label, unit, days, limits, change_limit, source = SERIES[key]
    out = dict(id=key, label=label, unit=unit, maxAgeDays=days, source=source,
               url='https://fred.stlouisfed.org/series/'+key, thresholds=limits)
    if not rows:
        return dict(out, status='missing', value=None, asOf=None, severity=None)
    d, v = rows[-1]
    cutoff = (date.fromisoformat(d)-timedelta(days=28)).isoformat()
    prior = next(((pd,pv) for pd,pv in reversed(rows[:-1]) if pd <= cutoff), None)
    change = v-prior[1] if prior else None
    severity = sum(v >= n for n in limits) if limits else None
    if severity is not None and change is not None and change_limit and change >= change_limit:
        severity = max(1, severity)
    return dict(out, status='ready' if 0 <= age(d,today) <= days else 'stale',
                value=v, asOf=d, previous=prior[1] if prior else None,
                previousDate=prior[0] if prior else None, change=change, severity=severity)

def funding(sofr, iorb, today):
    other = dict(iorb)
    matched = [(d, (v-other[d])*100) for d,v in sofr if d in other]
    out = dict(id='FUNDING',label='SOFR − IORB',unit='bp',maxAgeDays=5,
               source='New York Fed / Federal Reserve Board via FRED',
               url='https://fred.stlouisfed.org/series/SOFR', thresholds=[5,15,30])
    if len(matched)<3:
        return dict(out,status='missing',value=None,asOf=None,severity=None)
    d,v=matched[-1]
    persistent=sum(x>=15 for _,x in matched[-3:])>=2
    severity=3 if persistent and v>=30 else 2 if persistent else 1 if v>=5 else 0
    return dict(out,status='ready' if age(d,today)<=5 else 'stale',asOf=d,value=round(v,3),
                previous=round(matched[-2][1],3),previousDate=matched[-2][0],
                change=round(v-matched[-2][1],3),severity=severity,persistent=persistent)

def credit_state(indicators):
    # NFCI and STLFSI overlap: combine as one family, not independent votes.
    by={x['id']:x for x in indicators if x['status']=='ready' and x.get('severity') is not None}
    groups=[]
    conditions=[by[k]['severity'] for k in ('NFCI','STLFSI4') if k in by]
    if conditions: groups.append(max(conditions))
    for k in ('FUNDING','DRTSCILM'):
        if k in by: groups.append(by[k]['severity'])
    bonds=[by[k]['severity'] for k in ('GZ_SPREAD','EBP') if k in by]
    if bonds: groups.append(max(bonds))
    if not groups: return dict(status='unknown',score=None,coverage=0)
    score=round(statistics.mean(groups)/3*100)
    status='risk' if max(groups)>=3 or sum(v>=2 for v in groups)>=2 else 'watch' if max(groups)>=1 else 'stable'
    if len(groups)<3 and status=='stable': status='unknown'
    return dict(status=status,score=score,coverage=len(groups),expected=3)

def classify(title):
    for label,pattern,interpretation in TOPICS:
        if re.search(pattern,title,re.I):
            return label,interpretation
    return '기타 발표','시장 방향을 단정하지 않는 참고 발표입니다.'

def parse_news(text, name, now):
    items=[]
    for item in ET.fromstring(text).findall('.//item'):
        title=' '.join((item.findtext('title') or '').split())
        link=item.findtext('link') or ''
        if urlparse(link).scheme!='https' or urlparse(link).hostname!='www.federalreserve.gov': continue
        try:
            dt=parsedate_to_datetime(item.findtext('pubDate') or '')
            if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
            if not 0 <= (now-dt).total_seconds() <= 14*86400: continue
        except (ValueError,TypeError): continue
        topic,interpretation=classify(title)
        items.append(dict(title=title[:240],url=link,publishedAt=dt.isoformat(),source=name,
                          topic=topic,interpretation=interpretation,assessment='원문 검토 필요'))
    return items

def build(root=ROOT, now=None, fetcher=get):
    now=now or datetime.now(timezone.utc); today=now.date()
    target=root/'market/latest.json'
    old=json.loads(target.read_text()) if target.exists() else {}
    errors=[]; observations={}; indicators=[]
    old_by = {x['id']: x for x in old.get('indicators', [])}
    old_rows = old.get('observations', {})
    def fetch_series(key):
        rows, meta = collect_series(key, today, fetcher)
        return key, rows, meta
    with ThreadPoolExecutor(max_workers=2) as pool:
        for key,rows,meta in pool.map(fetch_series,SERIES):
            fetched = bool(rows)
            if not fetched: rows = [(d,v) for d,v in old_rows.get(key, []) if 0 <= age(d,today) < 900 and isinstance(v,(int,float)) and math.isfinite(v)]
            observations[key]=rows
            entry=summarize(key,rows,today)
            if fetched:
                entry.update(meta, fromCache=False, lastSuccessAt=now.isoformat(), lastAttemptAt=now.isoformat())
            else:
                error = meta['fetchError']; errors.append(key+': '+error)
                if rows: entry['lastSuccessAt'] = old_by.get(key, {}).get('lastSuccessAt')
                entry = retain_observation(entry, entry if rows else old_by.get(key), today, error, now)
            entry['frequency'] = 'quarterly' if key=='DRTSCILM' else 'weekly' if key in ('NFCI','STLFSI4') else 'daily'
            indicators.append(entry)
    fund = funding(observations.get('SOFR',[]),observations.get('IORB',[]),today)
    fund['frequency'] = 'daily'
    inputs_ok = all(x['fetchStatus']=='ready' for x in indicators if x['id'] in ('SOFR','IORB'))
    if inputs_ok and fund['value'] is not None:
        fund.update(fromCache=False, fetchStatus='ready', lastSuccessAt=now.isoformat(), lastAttemptAt=now.isoformat())
    else:
        if fund['value'] is not None: fund['lastSuccessAt'] = old_by.get('FUNDING', {}).get('lastSuccessAt')
        fund = retain_observation(fund, fund if fund['value'] is not None else old_by.get('FUNDING'), today, '동일 날짜 SOFR·IORB 자료 갱신 확인 필요', now)
    indicators.append(fund)
    try:
        bonds = bond_spreads(fetcher(EBP_URL), today)
        if any(q['value'] is None for q in bonds): raise ValueError('No valid bond observations')
        for q in bonds: q.update(fetchStatus='ready', fromCache=False, lastSuccessAt=now.isoformat(), lastAttemptAt=now.isoformat())
        indicators.extend(bonds)
    except Exception as exc:
        error = type(exc).__name__; errors.append('Fed bond spread: '+error)
        indicators.extend(retain_observation(q, old_by.get(q['id']), today, error, now) for q in bond_spreads('', today))
    news=[]; feeds=[]
    for name,url in FEEDS:
        try:
            news.extend(parse_news(fetcher(url),name,now));feeds.append(dict(name=name,url=url,status='ready'))
        except Exception as exc:
            feeds.append(dict(name=name,url=url,status='unavailable'));errors.append(name+': '+type(exc).__name__)
    unique={x['url']:x for x in news}
    news=sorted(unique.values(),key=lambda x:x['publishedAt'],reverse=True)[:15]
    payload=dict(schemaVersion=2,model='public-early-warning-v1',generatedAt=now.isoformat(),observations=observations,
                 indicators=indicators,credit=credit_state(indicators),news=news,feeds=feeds,errors=errors,
                 newsScope='Fed 공식 발표·연설, 최근 14일. 키워드 주제 분류이며 기사 본문 분석이나 악재 확정이 아님. 기업뉴스·실적·사모신용 환매 전체를 감시하지 않음.',
                 exclusions=['HY/CCC OAS와 MOVE 수치 미재배포','사모신용 환매·BDC 부실·CLO 직접 측정 아님'],
                 referenceLinks=[dict(label='HY OAS 원본',url='https://fred.stlouisfed.org/series/BAMLH0A0HYM2'),
                                 dict(label='CCC OAS 원본',url='https://fred.stlouisfed.org/series/BAMLH0A3HYC')])
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix('.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,indent=2));temp.replace(target)
    print(json.dumps(dict(credit=payload['credit'],news=len(news),errors=errors)))
    for error in errors: print('::warning title=Market indicator collection delayed::'+error)
    return payload

if __name__=='__main__': build()
