"""Audit three fixed candidates and a past-only selector on saved OOS results.

This is retrospective research, not a new live forecast or a trading backtest.
Selection is based only on outcome dates earlier than each evaluation origin.
"""
import json
import math
import statistics
from datetime import datetime,timezone
from pathlib import Path
from build_forecasts import atomic_json

ROOT=Path(__file__).resolve().parents[1]
MODELS=('noChange','trend','learned')

def prediction(row,model):
    return 0.0 if model=='noChange' else row['trend'] if model=='trend' else row['pred']

def score(rows,model):
    if not rows:return dict(n=0,dates=0,mae=None,p90Error=None,worstError=None,directionAccuracy=None)
    errors=sorted(abs(math.expm1(q['y'])-math.expm1(prediction(q,model))) for q in rows)
    return dict(n=len(rows),dates=len({q['origin'] for q in rows}),mae=statistics.mean(errors),
        p90Error=errors[math.ceil(.9*len(errors))-1],worstError=errors[-1],
        directionAccuracy=statistics.mean((q['y']>0)-(q['y']<0)==(prediction(q,model)>0)-(prediction(q,model)<0) for q in rows))

def compare(rows):
    choices=[];selected=[]
    for origin in sorted({q['origin'] for q in rows}):
        past=[q for q in rows if q['targetDate']<origin]
        if len({q['origin'] for q in past})<2:continue
        # Fixed MAE objective, deterministic simpler-model tie breaker.
        chosen=min(MODELS,key=lambda m:score(past,m)['mae'])
        test=[q for q in rows if q['origin']==origin]
        choices.append(dict(origin=origin,chosen=chosen,selectionDates=len({q['origin'] for q in past}),
                            selectionTargetThrough=max(q['targetDate'] for q in past),testRows=len(test)))
        selected.extend(dict(q,pred=prediction(q,chosen)) for q in test)
    # Compare all candidates on exactly the dates evaluated by the selector.
    dates={q['origin'] for q in selected};matched=[q for q in rows if q['origin'] in dates]
    return dict(allDates={m:score(rows,m) for m in MODELS},
                laterDates={m:score(matched,m) for m in MODELS},selector=score(selected,'learned'),choices=choices,
                status='research',liveForecastChanged=False)

def build(root=ROOT):
    out=dict(schemaVersion=1,model='past-only-comparison-v1',generatedAt=datetime.now(timezone.utc).isoformat(),horizons={},
             note='과거 기록을 이용한 소급 비교. 모델 선택 시점 이후 결과만 평가하지만, 이 선택 규칙 자체는 아직 실전 검증 전입니다. 매매 수익률·최대 낙폭 검증이 아닙니다.')
    for h in (21,84,252):
        path=root/'ml/validation'/f'{h}.json'
        if not path.exists():continue
        source=json.loads(path.read_text());rows=source.get('outcomes',[])
        result=compare(rows);result['sourceGeneratedAt']=source.get('generatedAt');result['sourceModel']=source.get('model')
        out['horizons'][str(h)]=result
    atomic_json(root/'ml/comparison.json',out)
    print(json.dumps({h:{'laterDates':q['selector']['dates'],'selectorMAE':q['selector']['mae']} for h,q in out['horizons'].items()}))
    return out

if __name__=='__main__':build()
