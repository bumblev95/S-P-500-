"""Score first-issued forecasts separately from reconstructed backtests."""
import json,math
from datetime import datetime,timezone
from pathlib import Path
from build_forecasts import atomic_json,clean_history
ROOT=Path(__file__).resolve().parents[1]

def evaluate(entry,record,issued,history):
    f=record.get('forecast',{});h=f.get('horizon');asof=entry.get('asOf','')
    result=dict(asOf=asof,issuedAt=issued,horizon=h,status='pending',eligible=record.get('status')=='eligible')
    if not isinstance(h,int) or h<1 or not issued or issued[:10]>asof:
        return dict(result,status='excluded',reason='발표 시점 또는 기록 확인 필요')
    dates={q['date']:i for i,q in enumerate(history)};i=dates.get(asof)
    if i is None:return dict(result,status='unavailable',reason='발표일 가격 이력 없음')
    anchor=f.get('anchor')
    if not isinstance(anchor,(int,float)) or anchor<=0 or abs(history[i]['close']/anchor-1)>.005:
        return dict(result,status='excluded',reason='분할·가격 수정 확인 필요')
    if i+h>=len(history):return result
    target=history[i+h];actual=target['close']/anchor-1;pred=f['base']/anchor-1
    if target['date']<=issued[:10]:return dict(result,status='excluded',reason='결과 이후 발표된 기록')
    direction=lambda r:1 if r>.02 else -1 if r<-.02 else 0
    return dict(result,status='scored',targetDate=target['date'],actualReturn=actual,predictedReturn=pred,
                error=abs(actual-pred),baselineError=abs(actual),directionHit=direction(actual)==direction(pred),
                rangeHit=f['bear']<=target['close']<=f['bull'])

def summary(rows):
    selected=[r for r in rows if r['eligible']];done=[r for r in selected if r['status']=='scored'];n=len(done)
    return dict(scored=n,pending=sum(r['status']=='pending' for r in selected),
                unavailable=sum(r['status']=='unavailable' for r in selected),excluded=sum(r['status']=='excluded' for r in selected),
                researchRecords=sum(not r['eligible'] for r in rows),
                mae=sum(r['error'] for r in done)/n if n else None,
                baselineMae=sum(r['baselineError'] for r in done)/n if n else None,
                directionAccuracy=sum(r['directionHit'] for r in done)/n if n else None,
                rangeCoverage=sum(r['rangeHit'] for r in done)/n if n else None,
                issueDates=len({r['asOf'] for r in done}))

def build(root=ROOT):
    rows=[];stocks={};seen=set();cache={}
    latest=json.loads((root/'ml/latest.json').read_text())
    current_model=latest.get('model')
    for path in sorted((root/'ml/archive').glob('*.json')):
        a=json.loads(path.read_text());model=a.get('model','unknown')
        if model!=current_model:continue
        for symbol,entry in a.get('stocks',{}).items():
            if symbol not in cache:
                hp=root/'prices/history'/f'{symbol}.json'
                if hp.exists():cache[symbol]=clean_history(json.loads(hp.read_text()).get('prices',[]))
                else:
                    if '_snapshot' not in cache:cache['_snapshot']=json.loads((root/'forecasts/latest.json').read_text()).get('stocks',{})
                    cache[symbol]=clean_history(cache['_snapshot'].get(symbol,{}).get('history',[]))
            for horizon,p in entry.get('predictions',{}).items():
                key=(model,symbol,entry.get('asOf'),horizon)
                if key in seen:continue
                seen.add(key)
                r=dict(evaluate(entry,p,a.get('issuedAt',''),cache[symbol]),symbol=symbol,model=model)
                rows.append(r);stocks.setdefault(symbol,{}).setdefault(horizon,[]).append(r)
    payload=dict(schemaVersion=1,model=current_model,generatedAt=datetime.now(timezone.utc).isoformat(),
                 horizons={str(h):summary([r for r in rows if r['horizon']==h]) for h in (21,84,252)},
                 stocks={s:{h:dict(summary=summary(rs),records=rs[-60:]) for h,rs in hs.items()} for s,hs in stocks.items()},
                 note='실제 발표 후 결과를 추적한 예측 평가. 매매 수익률 아님. 매일 발행한 예측의 평가 기간은 서로 겹칠 수 있어 독립 표본이 아닙니다.')
    atomic_json(root/'ml/live-results.json',payload)
    print(json.dumps(payload['horizons']));return payload

if __name__=='__main__':build()
