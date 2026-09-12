"""Immutable public forecast ledger, prospective scoring and conservative promotion.

No reconstructed predictions are backdated. All captured forecasts are research
forecasts, including withheld outputs. No order execution or user trade data.
"""
import csv
import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from build_forecasts import atomic_json, clean_history
ROOT = Path(__file__).resolve().parents[1]

def read(root, path, default=None):
    p = root / path
    return json.loads(p.read_text()) if p.exists() else (default if default is not None else {})

def finite(x): return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
def positive(x): return finite(x) and x > 0
def timestamp(x):
    try: return datetime.fromisoformat(x.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError): return None

def key(r): return '|'.join(str(r[k]) for k in ('assetClass','symbol','asOf','horizon','model'))
def quantile(values, p):
    if not values: return None
    a=sorted(values); i=(len(a)-1)*p; j=int(i)
    return a[j]+(a[min(j+1,len(a)-1)]-a[j])*(i-j)

def capture(root, now):
    rows=[]; stock=read(root,'ml/latest.json'); spot=read(root,'crypto/learned.json'); forecasts=read(root,'forecasts/latest.json')
    for asset, data, group in [('stocks',stock,'stocks'),('crypto',spot,'coins')]:
        generated=timestamp(data.get('generatedAt'))
        if not generated or not 0 <= (now-generated).total_seconds() <= 5*86400: continue
        for sym,e in data.get(group,{}).items():
            origin=timestamp(e.get('asOf'))
            if not origin or not 0 <= (now-origin).total_seconds() <= 5*86400: continue
            features=e.get('features',{}) if asset=='crypto' else forecasts.get('stocks',{}).get(sym,{})
            if asset=='stocks': features=features.get('inputs',{}) if features.get('asOf')==e.get('asOf') else {}
            for h,p in e.get('predictions',{}).items():
                f=p.get('forecast') or {}; anchor=f.get('anchor',e.get('anchor',e.get('price')))
                if not positive(anchor) or not positive(f.get('base')): continue
                lo=f.get('bear'); hi=f.get('bull')
                if lo is None and finite(f.get('lowLogReturn')): lo=anchor*math.exp(f['lowLogReturn'])
                if hi is None and finite(f.get('highLogReturn')): hi=anchor*math.exp(f['highLogReturn'])
                rows.append(dict(assetClass=asset,symbol=sym,asOf=e['asOf'],horizon=int(h),model=data['model'],anchor=anchor,base=f['base'],low=lo,high=hi,features=features,validation=p.get('validation',{}),eligible=p.get('status')=='eligible',sourceGeneratedAt=data['generatedAt'],issuedAt=now.isoformat(),source=e.get('source','Yahoo EOD'),kind='incumbent'))
    env=read(root,'research/environment.json'); generated=timestamp(env.get('generatedAt'))
    if generated and 0 <= (now-generated).total_seconds() <= 8*86400:
        for asset in ('stocks','crypto'):
            for h,block in env.get(asset,{}).items():
                for sym,e in block.get('predictions',{}).items():
                    origin=timestamp(e.get('asOf'))
                    if not origin or not 0 <= (now-origin).total_seconds() <= 5*86400: continue
                    for variant in ('balanced','enriched'):
                        if not positive(e.get(variant)) or not positive(e.get('anchor')): continue
                        # balanced interval is not reused for a different point forecast.
                        band=e.get('range',{}) if variant=='balanced' else {}
                        v=e.get('validation',{}).get(variant,{})
                        rows.append(dict(assetClass=asset,symbol=sym,asOf=e['asOf'],horizon=int(h),model=env['model']+':'+variant,anchor=e['anchor'],base=e[variant],low=band.get('low'),high=band.get('high'),features=e.get('inputValues',{}),validation=v,eligible=False,sourceGeneratedAt=env['generatedAt'],issuedAt=now.isoformat(),source='Yahoo EOD' if asset=='stocks' else 'Yahoo Finance spot daily USD',kind='challenger'))
    return rows, {'stocks':stock.get('model'), 'crypto':spot.get('model')}

def score(r, history, now, calendar=None):
    out=dict(r,status='pending'); issued=timestamp(r.get('issuedAt')); origin=timestamp(r.get('asOf'))
    if not issued or not origin or issued>now or origin>issued or not positive(r.get('anchor')) or not positive(r.get('base')):
        return dict(out,status='excluded',reason='발표 시각·기준가 검증 실패')
    hist=clean_history(history); dates={p['date']:i for i,p in enumerate(hist)}; i=dates.get(r['asOf']); h=r['horizon']
    if not isinstance(h,int) or h<=0: return dict(out,status='excluded',reason='기간 오류')
    if i is None: return dict(out,status='unavailable',reason='원래 기준일 가격 이력 없음')
    if abs(hist[i]['close']/r['anchor']-1)>.005: return dict(out,status='excluded',reason='기준가 수정·분할·출처 차이 확인 필요')
    if r['assetClass']=='crypto':
        target=(origin+timedelta(days=h)).date().isoformat(); j=dates.get(target)
        if j is None: return dict(out,status='pending' if hist[-1]['date']<target else 'unavailable')
    else:
        if calendar:
            sessions=sorted({d for d in calendar if d>=r['asOf']})
            if not sessions or sessions[0]!=r['asOf']: return dict(out,status='unavailable',reason='시장 거래일 정렬 확인 필요')
            if h>=len(sessions): return out
            target=sessions[h]; j=dates.get(target)
            if j is None: return dict(out,status='unavailable',reason='목표 거래일 종가 없음')
        else:
            if i+h>=len(hist): return out
            j=i+h; target=hist[j]['date']
    # Conservative: target's entire date must be after issue date and already complete.
    if target<=issued.date().isoformat(): return dict(out,status='excluded',reason='목표일 이후 기록된 예측')
    if target>=now.date().isoformat(): return out
    actual=hist[j]['close']; pred_return=r['base']/r['anchor']-1; actual_return=actual/r['anchor']-1
    direction=lambda x: 1 if x>.02 else -1 if x<-.02 else 0
    return dict(out,status='scored',targetDate=target,actual=actual,mape=abs(r['base']/actual-1),baselineMape=abs(r['anchor']/actual-1),returnError=abs(pred_return-actual_return),directionHit=direction(pred_return)==direction(actual_return),rangeHit=r['low']<=actual<=r['high'] if positive(r.get('low')) and positive(r.get('high')) else None)

def summarize(rows):
    done=[r for r in rows if r['status']=='scored']; n=len(done)
    return dict(n=n,dates=len({r['asOf'] for r in done}),pending=sum(r['status']=='pending' for r in rows),unavailable=sum(r['status']=='unavailable' for r in rows),excluded=sum(r['status']=='excluded' for r in rows),mape=statistics.mean(r['mape'] for r in done) if n else None,baselineMape=statistics.mean(r['baselineMape'] for r in done) if n else None,p90Error=quantile([r['mape'] for r in done],.9),directionAccuracy=statistics.mean(r['directionHit'] for r in done) if n else None)

def paired_gate(rows, incumbent, challenger):
    """Same symbol/date/anchor/target, date-equal weights; non-overlapping windows."""
    groups={}
    for r in rows:
        if r['status']=='scored' and r['model'] in (incumbent,challenger): groups.setdefault((r['symbol'],r['asOf'],r['targetDate']),{})[r['model']]=r
    pairs=[(g[incumbent],g[challenger]) for g in groups.values() if incumbent in g and challenger in g and abs(g[incumbent]['anchor']/g[challenger]['anchor']-1)<1e-6]
    dates=sorted({a['asOf'] for a,b in pairs}); chosen=[]; through=''
    for d in dates:
        if d<=through: continue
        chosen.append(d); through=max(a['targetDate'] for a,b in pairs if a['asOf']==d)
    pairs=[(a,b) for a,b in pairs if a['asOf'] in chosen]
    result=dict(challenger=challenger,dates=len(chosen),pairs=len(pairs),passed=False)
    if not pairs: return dict(result,reason='같은 조건의 실제 평가 결과 대기')
    av=[statistics.mean(a['mape'] for a,b in pairs if a['asOf']==d) for d in chosen]
    bv=[statistics.mean(b['mape'] for a,b in pairs if a['asOf']==d) for d in chosen]
    nv=[statistics.mean(a['baselineMape'] for a,b in pairs if a['asOf']==d) for d in chosen]
    a=statistics.mean(av); b=statistics.mean(bv); baseline=statistics.mean(nv)
    win=statistics.mean(y<x for x,y in zip(av,bv)); tail=quantile([q['mape'] for _,q in pairs],.9); oldtail=quantile([q['mape'] for q,_ in pairs],.9)
    passed=len(chosen)>=12 and len(pairs)>=30 and b<.95*min(a,baseline) and win>=.6 and tail<=oldtail and statistics.mean(bv[-3:])<statistics.mean(av[-3:])
    return dict(result,passed=passed,incumbentMape=a,challengerMape=b,baselineMape=baseline,winRate=win,reason='승격 기준 통과' if passed else '12개 비중첩 시점·30개 쌍·오차 5% 개선·시점 우위 60%·큰 오차/최근 성적 기준 미충족',evaluatedThrough=max(q['targetDate'] for pair in pairs for q in pair))

def change(current, previous):
    if not previous: return dict(status='waiting',text='첫 기록을 저장했습니다. 다음 기준일의 전망부터 변화 이유를 비교합니다.')
    old=previous['base']/previous['anchor']-1; new=current['base']/current['anchor']-1; delta=new-old
    facts=[]
    mapping={'return1m':'최근 1개월 수익률','return30':'최근 30일 모멘텀(로그수익률)','volatility4m':'연환산 변동성','vol30':'최근 30일 연환산 변동성','revenueGrowth':'매출 성장률','funding7d':'7일 누적 펀딩비'}
    for k,label in mapping.items():
        a=previous.get('features',{}).get(k); b=current.get('features',{}).get(k)
        if finite(a) and finite(b) and abs(b-a)>1e-6: facts.append(dict(label=label,previous=a,current=b,delta=b-a))
    return dict(status='ready',previousAsOf=previous['asOf'],currentAsOf=current['asOf'],previousReturn=old,currentReturn=new,delta=delta,previousTarget=previous['base'],currentTarget=current['base'],facts=facts[:2],text='지난 기준일보다 예상 수익률이 '+('높아졌습니다.' if delta>.001 else '낮아졌습니다.' if delta<-.001 else '비슷합니다.'),note='같은 모델·기간의 서로 다른 목표일을 비교합니다. 지표 변화는 동시 관측 근거이며 모델 기여도나 인과관계로 확인된 것은 아닙니다.')

def build(root=ROOT, now=None):
    now=now or datetime.now(timezone.utc); folder=root/'decision/ledger'; folder.mkdir(parents=True,exist_ok=True)
    new,defaults=capture(root,now); ledger=[]
    for p in sorted(folder.glob('*.json')): ledger.extend(json.loads(p.read_text())['records'])
    existing={key(r) for r in ledger}; added=[r for r in new if key(r) not in existing]
    if added:
        digest=hashlib.sha256(json.dumps(added,sort_keys=True).encode()).hexdigest()[:12]
        atomic_json(folder/(now.strftime('%Y%m%dT%H%M%S')+'-'+digest+'.json'),dict(recordedAt=now.isoformat(),records=added)); ledger.extend(added)
    snapshots=read(root,'forecasts/latest.json').get('stocks',{}); crypto=read(root,'crypto/latest.json').get('coins',{}); cache={}
    def history(r):
        k=(r['assetClass'],r['symbol'],r['source'])
        if k not in cache:
            if r['assetClass']=='stocks': cache[k]=read(root,'prices/history/'+r['symbol']+'.json').get('prices',snapshots.get(r['symbol'],{}).get('history',[]))
            elif r['source'].startswith('Yahoo'): cache[k]=read(root,'crypto/research-history/'+r['symbol']+'.json').get('prices',[])
            else: cache[k]=crypto.get(r['symbol'],{}).get('spotHistory',[])
        return cache[k]
    previous_scores=read(root,'decision/outcomes.json').get('records',{})
    scored=[]
    calendar=[q['date'] for q in snapshots.get('SPY',{}).get('history',[])]
    for r in ledger:
        rid=key(r); stored=previous_scores.get(rid)
        result=dict(r,**stored) if stored else score(r,history(r),now,calendar)
        if result['status']=='scored' and not stored: previous_scores[rid]={k:v for k,v in result.items() if k not in r}
        scored.append(result)
    atomic_json(root/'decision/outcomes.json',dict(records=previous_scores))
    registry=read(root,'decision/registry.json',{'champions':{},'events':[]}); groups={}; changes={}; current={}
    for asset in ('stocks','crypto'):
        groups[asset]={}; changes[asset]={}; current[asset]={}
        horizons=sorted({r['horizon'] for r in scored if r['assetClass']==asset})
        for h in horizons:
            rs=[r for r in scored if r['assetClass']==asset and r['horizon']==h]; models=sorted({r['model'] for r in rs}); regkey=asset+':'+str(h)
            champion=registry['champions'].get(regkey,defaults[asset]); registry['champions'][regkey]=champion
            gates=[paired_gate(rs,champion,m) for m in models if m!=champion]
            for gate in gates:
                available=any(r['assetClass']==asset and r['horizon']==h and r['model']==gate['challenger'] and positive(r.get('low')) and positive(r.get('high')) and r['low']<=r['base']<=r['high'] for r in new)
                if not available: gate.update(passed=False,reason='최신 예측과 자체 참고 범위 확인 대기')
            passed=sorted([g for g in gates if g['passed']],key=lambda g:g['challengerMape'])
            if passed:
                winner=passed[0]; registry['champions'][regkey]=winner['challenger']; registry['events'].append(dict(at=now.isoformat(),assetClass=asset,horizon=h,previous=champion,model=winner['challenger'],evidence=winner)); champion=winner['challenger']
            bysymbol={}
            for sym in sorted({r['symbol'] for r in rs}):
                own=[r for r in rs if r['symbol']==sym]; bysymbol[sym]={m:summarize([r for r in own if r['model']==m]) for m in models if any(r['model']==m for r in own)}
                matches=sorted([r for r in own if r['model']==champion],key=lambda r:(r['asOf'],r['issuedAt']))
                if matches:
                    cur=matches[-1]; prev=next((r for r in reversed(matches[:-1]) if r['asOf']<cur['asOf']),None)
                    changes[asset].setdefault(sym,{})[str(h)]=change(cur,prev)
                    # Current default comes only from this run's source snapshots, never a stale ledger.
                    fresh=next((r for r in new if key(r)==key(cur)),None)
                    if fresh and champion!=defaults[asset]: current[asset].setdefault(sym,{})[str(h)]=dict(cur,promoted=champion!=defaults[asset])
            groups[asset][str(h)]=dict(champion=champion,models={m:summarize([r for r in rs if r['model']==m]) for m in models},symbols=bysymbol,gates=gates)
    # Symbol-level stock backtest tail errors use the same saved outcomes as existing MAE.
    tails={}
    for p in (root/'ml/validation').glob('*.json'):
        d=json.loads(p.read_text())
        for r in d.get('outcomes',[]):
            if finite(r.get('pred')) and finite(r.get('y')): tails.setdefault(r['symbol'],{}).setdefault(p.stem,[]).append(abs(math.expm1(r['pred'])-math.expm1(r['y'])))
    tails={s:{h:quantile(v,.9) for h,v in hs.items()} for s,hs in tails.items()}
    earnings={}
    ep=root/'fundamentals/latest_fundamentals.csv'
    if ep.exists():
        for row in csv.DictReader(ep.open()):
            if row.get('nextEarningsDate'): earnings[row['symbol']]=dict(date=row['nextEarningsDate'],updatedAt=row.get('updatedAt'))
    payload=dict(earnings=earnings,schemaVersion=1,generatedAt=now.isoformat(),groups=groups,changes=changes,current=current,stockTailErrors=tails,stockValidationGeneratedAt=read(root,'ml/latest.json').get('generatedAt'),recordCount=len(ledger),newRecords=len(added),promotionPolicy='같은 종목·기준일·기준가·목표일. 12개 비중첩 시점과 30개 비교쌍, 불변/기존 모델 대비 평균 가격 오차 5% 개선, 시점 우위 60%, 큰 오차 악화 없음, 최근 3시점 개선. 통과 후 향후 기본 모델만 변경.',note='실제 공개 기록을 만든 이후의 성적입니다. 소급 백테스트나 매매 수익률이 아닙니다. 과거 날짜를 기준으로 오늘 기록한 예측은 오늘 이후 결과만 평가합니다. ±2%는 중립 방향으로 집계합니다.')
    atomic_json(root/'decision/registry.json',registry); atomic_json(root/'decision/latest.json',payload)
    print(json.dumps(dict(records=len(ledger),new=len(added),scored=sum(r['status']=='scored' for r in scored),promotions=len(registry['events']))))
    return payload
if __name__=='__main__': build()
