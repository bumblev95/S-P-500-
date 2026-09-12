"""Small neural-network research; never mutates the public trading policy."""
import json,hashlib,subprocess,sys,warnings
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
VERSION='pattern-mlp-16-8-v1'
FEATURES=['rsi','atr_fraction','ema20_atr','ema50_atr','relative_volume','efficiency','body_fraction','lower_wick','upper_wick','return_4','return_16','return_64','hour_trend','side','retest','candle','false_break','BTC','ETH','SOL']

def split_rows(rows,previous_end=0):
    times=sorted({r['at'] for r in rows})
    if len(times)<20:return [],[],[],{}
    validation_start=times[int(len(times)*.6)]
    test_start=max(times[int(len(times)*.8)],previous_end+1)
    embargo=8*900000
    train=[r for r in rows if r['labelEnd']<validation_start-embargo]
    validation=[r for r in rows if r['at']>=validation_start and r['labelEnd']<test_start-embargo]
    test=[r for r in rows if r['at']>=test_start]
    return train,validation,test,dict(validationStart=validation_start,testStart=test_start,embargoMs=embargo)

def due(root=ROOT,now=None):
    now=now or int(datetime.now(timezone.utc).timestamp()*1000)
    p=root/'simulation/research/latest.json'
    if not p.exists():return True
    previous=json.loads(p.read_text())
    return previous.get('version')!=VERSION or now-previous['generatedAt']>=7*86400000

def train(root=ROOT,now=None):
    now=now or int(datetime.now(timezone.utc).timestamp()*1000)
    folder=root/'simulation/research';folder.mkdir(parents=True,exist_ok=True)
    latest=folder/'latest.json'
    if not due(root,now):print('Frozen research retained; next experiment after seven days');return
    import numpy as np
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
    from sklearn.metrics import brier_score_loss,accuracy_score
    import sklearn
    market=root/'simulation/market.json'
    payload=subprocess.check_output(['node',str(root/'scripts/pattern_research_data.cjs'),str(market)],cwd=root)
    rows=json.loads(payload)
    previous=json.loads(latest.read_text()) if latest.exists() else {}
    prior_end=previous.get('evaluatedThrough',0)
    training,validation,test,bounds=split_rows(rows,prior_end)
    bars=json.loads(market.read_text())['crypto']['BTC']['frames']['15m']
    days=(bars[-1]['end']-bars[0]['t'])/86400000
    report=dict(version=VERSION,generatedAt=now,model='MLP · 은닉층 16 → 8',status='자료 부족',deployed=False,
                dataDays=days,counts=dict(train=len(training),validation=len(validation),test=len(test)),bounds=bounds,
                evaluatedThrough=prior_end,sourceHash=hashlib.sha256(market.read_bytes()).hexdigest(),
                nextReviewAt=now+7*86400000,features=FEATURES,sklearnVersion=sklearn.__version__,reasons=[],
                notes=['학습 60% · 선택 20% · 뒤쪽 평가 20%, 코인 공통 시간 경계와 8봉 간격.',
                       '첫 결과는 규칙을 이미 연구한 자료의 탐색 평가입니다. 앞으로의 모의 성적과 구분합니다.',
                       '신호별 학습 표본은 겹칠 수 있어 독립 거래 수가 아닙니다. 계좌 성적은 별도 체결 엔진으로 계산합니다.',
                       '학습은 주 1회 검토하고 이미 평가한 기간을 다음 실험의 새 평가 성적으로 재사용하지 않습니다.',
                       '예측 점수는 보정된 적중 확률이 아닙니다. 신경망은 실험 중이며 진행 계좌에 적용하지 않습니다.'])
    if len(training)<40 or len(validation)<10 or len(test)<10 or len({r['y'] for r in training})<2:
        report['reasons']=['학습 40개·선택 10개·새 평가 10개 이상의 유효 신호 표본이 필요합니다.']
    else:
        def xy(rs):return np.array([r['x'] for r in rs]),np.array([r['y'] for r in rs])
        x,y=xy(training);xv,yv=xy(validation);xt,yt=xy(test)
        nn=make_pipeline(StandardScaler(),MLPClassifier(hidden_layer_sizes=(16,8),alpha=1.,solver='lbfgs',max_iter=500,random_state=42))
        linear=make_pipeline(StandardScaler(),LogisticRegression(C=1.,max_iter=500,random_state=42))
        with warnings.catch_warnings(record=True) as caught:
            nn.fit(x,y);linear.fit(x,y)
        report['trainingWarnings']=[str(w.message) for w in caught]
        val_scores=nn.predict_proba(xv)[:,1]
        options=[]
        for threshold in (.5,.6,.7):
            chosen=[r for r,s in zip(validation,val_scores) if s>=threshold]
            options.append(dict(threshold=threshold,accepted=len(chosen),sumNetR=sum(r['netR'] for r in chosen)))
        eligible=[v for v in options if v['accepted']>=10]
        selected=max(eligible,key=lambda v:(v['sumNetR'],-v['threshold'])) if eligible else options[0]
        scores=nn.predict_proba(xt)[:,1];base_scores=linear.predict_proba(xt)[:,1]
        majority=float(y.mean())
        report.update(status='검증 보류',threshold=selected['threshold'],validationOptions=options,
                      validationQualified=bool(eligible),evaluatedThrough=max(r['labelEnd'] for r in test),
                      evaluationStart=min(r['at'] for r in test),evaluationEnd=max(r['labelEnd'] for r in test),
                      metrics=dict(neuralBrier=float(brier_score_loss(yt,scores)),linearBrier=float(brier_score_loss(yt,base_scores)),
                                   constantBrier=float(brier_score_loss(yt,np.full(len(yt),majority))),
                                   profitClassificationAccuracy=float(accuracy_score(yt,scores>=.5))))
        request=dict(marketPath=str(market),start=report['evaluationStart'],end=report['evaluationEnd'],threshold=selected['threshold'],
                     rows=[dict(r,score=float(score)) for r,score in zip(test,scores)])
        report['accounts']=json.loads(subprocess.check_output(['node',str(root/'scripts/evaluate_pattern_research.cjs')],input=json.dumps(request).encode(),cwd=root))
        candidate=report['accounts']['neuralFilter'];control=report['accounts']['rules']
        gates={'90일 이상 가격 이력':days>=90,'평가 종료 거래 100건':candidate['trades']>=100,
               '비용 차감 후 수익 양수':candidate['return']>0,'동일 기간 규칙 계좌보다 수익 개선':candidate['return']>control['return'],
               '최대 낙폭 악화 없음':candidate['maxDrawdown']<=control['maxDrawdown'],
               '단순 모델보다 예측 오차 개선':report['metrics']['neuralBrier']<min(report['metrics']['linearBrier'],report['metrics']['constantBrier']),
               '선택 구간 표본 충족':bool(eligible),'학습 수렴 경고 없음':not bool(caught)}
        report['gates']=gates;report['reasons']=[k+' 미충족' for k,v in gates.items() if not v]
        if not report['reasons']:report['status']='후속 모의실험 후보';report['reasons']=['별도 발표 후 모의 평가를 거쳐야 적용할 수 있습니다.']
        scaler,model=nn.steps[0][1],nn.steps[1][1]
        weights=dict(version=VERSION,features=FEATURES,mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
                     coefs=[v.tolist() for v in model.coefs_],intercepts=[v.tolist() for v in model.intercepts_],classes=model.classes_.tolist(),threshold=selected['threshold'])
        (folder/(str(now)+'-model.json')).write_text(json.dumps(weights))
    report['sampleHash']=hashlib.sha256(payload).hexdigest()
    (folder/(str(now)+'-samples.json')).write_bytes(payload)
    frozen=folder/(str(now)+'-report.json');frozen.write_text(json.dumps(report,ensure_ascii=False))
    latest.write_text(frozen.read_text());print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    if '--due' in sys.argv:print('true' if due() else 'false')
    else:train()
