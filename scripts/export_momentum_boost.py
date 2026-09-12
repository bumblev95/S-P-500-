"""Export an already fitted research model; this script never fits a new model."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import joblib
ROOT=Path(__file__).resolve().parents[1]
def export(research):
    report=json.loads((research/'futures-results.json').read_text())
    fold=next(f for f in report['folds'] if f['year']==2026)
    model_path=research/'models/futures-2026-boost.joblib';model=joblib.load(model_path)
    trees=[]
    for predictors in model._predictors:
        assert len(predictors)==1
        nodes=[]
        for n in predictors[0].nodes:
            assert not n['is_categorical']
            nodes.append({'leaf':bool(n['is_leaf']),'value':float(n['value']),'feature':int(n['feature_idx']),'threshold':float(n['num_threshold']),'left':int(n['left']),'right':int(n['right'])})
        trees.append(nodes)
    dest=ROOT/'simulation/momentum-boost';dest.mkdir(parents=True,exist_ok=True)
    obj={'schemaVersion':1,'id':'momentum14-breakout3-boost-2026-frozen-v1','features':report['features'],'baseline':float(model._baseline_prediction[0,0]),'trees':trees,'thresholdR':.10,
         'training':{'start':fold['trainStart'],'labelEnd':fold['trainLabelEnd'],'samples':fold['trainCount'],'validationStart':fold['validationStart'],'predictionYear':2026},
         'sourceModelSha256':hashlib.sha256(model_path.read_bytes()).hexdigest(),'sourceDataSha256':report['sourceHash'],'sourceProtocolSha256':report['protocolHash'],
         'note':'Already fitted 2026 boosting candidate. No retraining or selection using new forward results. Expected candidate netR, not a calibrated win probability.'}
    raw=json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False);(dest/'model.json').write_text(raw)
    rows=json.loads((research/'futures-samples.json').read_text())['rows'];rng=np.random.default_rng(42)
    indices=np.unique(np.r_[np.linspace(0,len(rows)-1,100,dtype=int),rng.integers(0,len(rows),100)])
    chosen=[rows[i] for i in indices];x=np.array([r['x'] for r in chosen]);scores=model.predict(x)
    fixtures={'modelSha256':hashlib.sha256(raw.encode()).hexdigest(),'rows':[{'x':r['x'],'score':float(p)} for r,p in zip(chosen,scores)]}
    (ROOT/'scripts/fixtures').mkdir(exist_ok=True);(ROOT/'scripts/fixtures/momentum-boost-parity.json').write_text(json.dumps(fixtures,separators=(',',':')))
    def compact(v):return {k:v[k] for k in ['return','cagr','maxDrawdown','sharpe','trades','winRate','expectancyR'] if k in v}
    research_summary={'period':{'start':report['continuous']['boost']['start'],'end':report['continuous']['boost']['end']},'results':{k:{**compact(report['continuous'][k]),'stressReturn':report['continuous'][k]['stress']['return']} for k in ['target6','breakout3','breakout3_one','boost']},
      'recent':{'start':report['recent']['boost']['start'],'end':report['recent']['boost']['end'],'results':{k:compact(report['recent'][k]) for k in ['target6','breakout3','breakout3_one','boost']}},
      'notes':['과거 결과를 본 뒤 선택한 후속 모의 후보입니다. 새로운 미래 검증이나 최고 수익 보장이 아닙니다.','ML 모델은 매 평가 연도마다 이전 자료로 학습했습니다. 앞으로는 검증에 사용한 2026 모델을 고정합니다.','최대 3종목과 1종목은 위험 배분도 다릅니다. 같은 날 시작한 비교 계좌에서 보유 한도와 ML의 효과를 구분합니다.','최근 약 20일은 모든 후보가 손실이었고 부스팅 종료 거래는 2건뿐입니다.','장기 자료는 Binance, 진행 모의계좌는 Hyperliquid여서 거래소와 펀딩 차이가 남습니다.']}
    (dest/'research.json').write_text(json.dumps(research_summary,ensure_ascii=False,separators=(',',':')))
    print('Model SHA256',fixtures['modelSha256'],'trees',len(trees),'parity fixtures',len(chosen))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('research',type=Path);export(parser.parse_args().research)
