"""E2 input audit: reconstruct dated quarters without changing production inputs."""
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import hashlib,json,math
from build_research_inputs import TAGS
from build_forecasts import atomic_json

ROOT=Path(__file__).resolve().parents[1]
FIELDS=('revenueYoY','netMargin','cashflowMargin','revenueYoYChange','netMarginChange','cashflowMarginChange')

def days(a,b):return (date.fromisoformat(a)-date.fromisoformat(b)).days

def facts_from(payload):
    facts=[]
    for metric in ('revenue','income','cashflow'):
        for rank,tag in enumerate(TAGS[metric]):
            for r in payload.get('facts',{}).get('us-gaap',{}).get(tag,{}).get('units',{}).get('USD',[]):
                if r.get('form') not in ('10-K','10-Q','10-K/A','10-Q/A'):continue
                try:
                    if not isinstance(r['val'],(float,int)) or not math.isfinite(r['val']):continue
                    if not 60<=days(r['end'],r['start'])<=400 or days(r['filed'],r['end'])<0:continue
                    facts.append(dict(metric=metric,tag=tag,rank=rank,start=r['start'],end=r['end'],
                        filed=r['filed'],accession=r.get('accn',''),value=r['val']))
                except (KeyError,ValueError,TypeError):continue
    return facts

def quarters_before(facts,origin):
    # Collapse repeated comparative facts only within the information set then available.
    versions={}
    for r in facts:
        if r['filed']>=origin:continue
        key=(r['metric'],r['tag'],r['start'],r['end'])
        old=versions.get(key)
        if old is None or (r['filed'],r['accession'])>(old['filed'],old['accession']):versions[key]=r
    groups=defaultdict(list);quarters=[]
    def add(r,start,value,evidence,method):
        quarters.append(dict(metric=r['metric'],tag=r['tag'],rank=r['rank'],start=start,end=r['end'],
            value=value,method=method,availableDate=max(x['filed'] for x in evidence),evidence=evidence,
            mixedAccessions=len({x['accession'] for x in evidence})>1))
    for r in versions.values():
        groups[(r['metric'],r['tag'],r['start'])].append(r)
        if 60<=days(r['end'],r['start'])<=120:add(r,r['start'],r['value'],[r],'standalone')
    for rows in groups.values():
        for r in rows:
            if days(r['end'],r['start'])<=120:continue
            prior=[p for p in rows if 60<=days(r['end'],p['end'])<=120]
            if prior:
                p=max(prior,key=lambda v:v['end'])
                start=(date.fromisoformat(p['end'])+timedelta(days=1)).isoformat()
                add(r,start,r['value']-p['value'],[r,p],'cumulative_difference')
    # Prefer a reported standalone quarter over a derived value for the same tag/period.
    unique={}
    for r in quarters:
        key=(r['metric'],r['tag'],r['start'],r['end'])
        old=unique.get(key)
        if old is None or (r['method']=='standalone',r['availableDate'])>(old['method']=='standalone',old['availableDate']):unique[key]=r
    return list(unique.values())

def snapshot(facts,origin,period_end=None):
    qq=quarters_before(facts,origin)
    revs=[r for r in qq if r['metric']=='revenue' and r['value']>0 and
          (r['end']==period_end if period_end else 0<=days(origin,r['end'])<=200)]
    if not revs:return None
    end=max(r['end'] for r in revs)
    rev=min((r for r in revs if r['end']==end),key=lambda r:(r['rank'],r['method']!='standalone',r['start']))
    def values_for(revenue):
        used=[revenue];values={}
        prior=[r for r in qq if r['metric']=='revenue' and r['tag']==revenue['tag'] and r['value']>0 and
               330<=days(revenue['end'],r['end'])<=400 and
               abs(days(revenue['start'],r['start'])-days(revenue['end'],r['end']))<=7]
        previous=max(prior,key=lambda r:r['end']) if prior else None
        values['revenueYoY']=revenue['value']/previous['value']-1 if previous else None
        if previous:used.append(previous)
        for metric,field in (('income','netMargin'),('cashflow','cashflowMargin')):
            matches=[r for r in qq if r['metric']==metric and r['start']==revenue['start'] and r['end']==revenue['end']]
            chosen=min(matches,key=lambda r:(r['rank'],r['method']!='standalone')) if matches else None
            values[field]=chosen['value']/revenue['value'] if chosen else None
            if chosen:used.append(chosen)
        return values,used
    values,used=values_for(rev)
    prior_quarter=[r for r in qq if r['metric']=='revenue' and r['tag']==rev['tag'] and r['value']>0 and 60<=days(rev['end'],r['end'])<=120]
    prev=max(prior_quarter,key=lambda r:r['end']) if prior_quarter else None
    prior_values,prior_used=values_for(prev) if prev else ({},[])
    used+=prior_used
    for field in FIELDS[:3]:
        values[field+'Change']=values[field]-prior_values[field] if values[field] is not None and prior_values.get(field) is not None else None
    evidence={json.dumps(e,sort_keys=True):e for q in used for e in q['evidence']}
    through=max(e['filed'] for e in evidence.values())
    if through>=origin:raise ValueError('Quarterly publication leakage')
    return dict(origin=origin,periodStart=rev['start'],periodEnd=rev['end'],availableThrough=through,
        revenue=rev['value'],**values,evidence=list(evidence.values()),
        derivedValues=sum(r['method']=='cumulative_difference' for r in used),
        mixedAccessionValues=sum(r['mixedAccessions'] for r in used))

def build(root=ROOT):
    folder=root/'research/experiments/2026-09-13'
    baseline=json.loads((root/'research/environment.json').read_text())
    members=json.loads((root/'research/universe.json').read_text())['members']
    releases=json.loads((root/'research/earnings.json').read_text())['issuers']
    input_audit=json.loads((folder/'input-audit.json').read_text())
    e1=json.loads((folder/'e1-ranking.json').read_text())
    groups=defaultdict(list)
    for symbol,r in members.items():groups[r['cik']].append(symbol)
    origins=[r['origin'] for r in baseline['stocks']['252']['folds']]
    current=max(r['lastDate'] for s,r in baseline['history'].items() if s in baseline['stockUniverse'])
    coverage={d:dict(n=0,available=0,fields={k:0 for k in FIELDS}) for d in origins+[current]}
    cohort={d:{r['symbol'] for r in baseline['stocks']['252']['outcomes'] if r['origin']==d} for d in origins}
    cohort[current]=set(baseline['stockUniverse'])
    cache=root/'research/source-cache';by_cik={};source_hashes={};errors=[]
    for p in sorted(cache.glob('*.json')):
        if p.name not in input_audit['secSourceHashes']:continue
        sha=hashlib.sha256(p.read_bytes()).hexdigest()
        if sha!=input_audit['secSourceHashes'][p.name]:raise ValueError('SEC source changed: '+p.name)
        payload=json.loads(p.read_text())
        if not isinstance(payload,dict) or 'cik' not in payload or 'facts' not in payload:continue
        cik=int(payload['cik'])
        if cik in groups:
            by_cik[cik]=p;source_hashes[p.name]=sha
    issuer_stats={};controls=[];evidence_samples={};total_snapshots=0;derived=0;mixed=0;restated_periods=0
    for num,(cik,symbols) in enumerate(sorted(groups.items())):
        facts=facts_from(json.loads(by_cik[cik].read_text())) if cik in by_cik else []
        versions=defaultdict(set)
        for r in facts:versions[(r['metric'],r['tag'],r['start'],r['end'])].add(r['value'])
        revised=sum(len(v)>1 for v in versions.values());restated_periods+=revised
        stats=dict(symbols=sorted(symbols),facts=len(facts),periodsWithMultipleReportedValues=revised,availableOrigins=0)
        for origin in origins+[current]:
            if not set(symbols)&cohort[origin]:continue
            c=coverage[origin];c['n']+=1;r=snapshot(facts,origin)
            if r:
                total_snapshots+=1;c['available']+=1;stats['availableOrigins']+=1
                for field in FIELDS:c['fields'][field]+=r[field] is not None
                derived+=r['derivedValues'];mixed+=r['mixedAccessionValues']
                if symbols[0] in ('AAPL','JPM','XOM','NVDA','MSFT') and origin in (origins[0],origins[-1],current):
                    evidence_samples[symbols[0]+' '+origin]=r
        for symbol in symbols:
            for release in releases.get(symbol,[]):
                # A release can precede the SEC filing: allow 60 days to locate its first filed equivalent.
                end=release['periodEnd'];cutoff=(date.fromisoformat(release['availableDate'])+timedelta(days=61)).isoformat()
                candidates=[d for d in sorted({r['filed'] for r in facts if r['end']==end and r['filed']<cutoff})
                            if d>=release['availableDate']]
                matched=None
                for filed in candidates:
                    s=snapshot(facts,(date.fromisoformat(filed)+timedelta(days=1)).isoformat(),end)
                    if s and s['netMargin'] is not None:matched=s;break
                if not matched:
                    controls.append(dict(symbol=symbol,periodEnd=end,status='unavailable'));continue
                expected_rev=release['revenue']*1e6;expected_income=release['netIncome']*1e6
                rev_delta=matched['revenue']-expected_rev
                income_delta=matched['netMargin']*matched['revenue']-expected_income
                controls.append(dict(symbol=symbol,periodEnd=end,status='matched' if abs(rev_delta)<=5e5 and abs(income_delta)<=5e5 else 'mismatch',
                    revenueDifference=rev_delta,incomeDifference=income_delta,availableThrough=matched['availableThrough']))
        issuer_stats[str(cik)]=stats
        if (num+1)%50==0:print('Quarter audit issuers:',num+1,flush=True)
    raw_price_files=0;event_files=0
    for symbol in baseline['stockUniverse']:
        p=root/'research/history'/(symbol+'.json');payload=json.loads(p.read_text())
        raw_price_files+=any('unadjustedClose' in r or 'rawClose' in r for r in payload['prices'])
        event_files+=bool(payload.get('splits') or payload.get('corporateActions'))
    summary=Counter(r['status'] for r in controls)
    result=dict(experiment='stock-validation-e2-input-audit-v1',completedAt=datetime.now(timezone.utc).isoformat(),
        codeHash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),sourceHashes=source_hashes,
        targetIssuers=len(groups),sourceIssuers=len(by_cik),issuersWithStandardFlowFacts=sum(v['facts']>0 for v in issuer_stats.values()),
        origins=coverage,issuerStats=issuer_stats,snapshots=total_snapshots,derivedValues=derived,mixedAccessionValues=mixed,
        periodsWithMultipleReportedValues=restated_periods,releaseControlCounts=dict(summary),releaseControls=controls,
        evidenceSamples=evidence_samples,errors=errors,
        valuation=dict(priceFiles=len(baseline['stockUniverse']),unadjustedPriceFiles=raw_price_files,corporateActionFiles=event_files,
            eligible=False,reason='Frozen cache stores adjusted closes only; historical shares and price split basis have not been reconciled.'),
        e1Selected=e1['selected'],e1SelectionEligible=e1['selectionEligible'],
        additionalConfigurationsFitted=0,
        fitDecision='blocked_by_e1_selection' if not e1['selectionEligible'] else 'pending_quarterly_quality_review',
        limitations=['Current SEC payload filtered by filed date, not a certified point-in-time vintage feed.',
            'Changed comparative values are retained with their filed dates; identical tag and fiscal start are required for cumulative differences.',
            'Derived quarters may combine filings. Original-company cross-checks cover NVDA/MSFT revenue and income, not all issuers or cash flows.',
            'Coverage is descriptive and does not establish incremental predictive value. Current constituent survivorship bias remains.'])
    atomic_json(folder/'e2-input-audit.json',result)
    lines=['# E2: 공시 시점과 분기 데이터 점검','',
        f"대상 {len(groups)}개 기업 중 SEC 원문 {len(by_cik)}개, 표준 분기 흐름 항목 {result['issuersWithStandardFlowFacts']}개.",
        f"공식 실적 자료와 교차 비교: {dict(summary)}.",
        f"동일 기간·태그에서 서로 다른 보고 값: {restated_periods}개. 공시일 이후에만 정정 값을 사용한다.",'',
        '| 예측 기준일 | 기업 수 | 분기 매출 | 매출 증가율 | 순이익률 | 현금흐름률 |','|---|---:|---:|---:|---:|---:|']
    for d,c in coverage.items():lines.append(f"| {d} | {c['n']} | {c['available']} | {c['fields']['revenueYoY']} | {c['fields']['netMargin']} | {c['fields']['cashflowMargin']} |")
    lines+=['',f"추가 학습 상태: {result['fitDecision']}. 실제 추가 학습 수: 0.",
        '역사적 밸류에이션: 원주가·주식 수·분할 기준을 일치시키는 자료가 없어 보류.',
        '분기 복원 가능성과 예측력 개선은 별개다. 파생 분기의 공시 혼합과 현금흐름 원문 확인 범위는 JSON에 기록한다.']
    (folder/'E2-RESULTS.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines),flush=True)
    return result

if __name__=='__main__':build()
