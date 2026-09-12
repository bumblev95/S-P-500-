"""Expanding multi-year training with separate calendar-year evaluations."""
import hashlib,json,os,subprocess,time,warnings
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import brier_score_loss
from train_pattern_research import FEATURES

ROOT=Path(__file__).resolve().parents[1]
CACHE=Path(os.environ.get('PAPER_LONG_CACHE','/tmp/paper-long-cache'))
VERSION='long-futures-wide-mlp-v1'
def stamp(year):return int(datetime(year,1,1,tzinfo=timezone.utc).timestamp()*1000)
def partition(rows,year):
    validation=stamp(year-1);test=stamp(year);end=stamp(year+1);gap=32*900000
    return ([r for r in rows if r['labelEnd']<validation-gap],
            [r for r in rows if validation<=r['at'] and r['labelEnd']<test-gap],
            [r for r in rows if test<=r['at'] and r['labelEnd']<end])

def train():
    folder=ROOT/'simulation/long-research';folder.mkdir(parents=True,exist_ok=True)
    market=CACHE/'market.json';manifest=json.loads((CACHE/'manifest.json').read_text())
    if manifest['errors']:raise ValueError('Archive collection incomplete; do not publish a partial-history experiment')
    now=int(time.time()*1000);end=min(v['end'] for v in manifest['coverage'].values())
    latest=folder/'latest.json';previous=json.loads(latest.read_text()) if latest.exists() else {}
    if previous.get('version')==VERSION and previous.get('dataEnd')==end:
        print('Same completed archive period; previous experiment retained');return
    source_hash=hashlib.sha256(market.read_bytes()).hexdigest()
    samples=CACHE/('wide-samples-'+source_hash[:16]+'.json')
    if not samples.exists():
        with samples.open('wb') as dest:subprocess.run(['node',str(ROOT/'scripts/pattern_research_data.cjs'),str(market),'wideRecovery'],stdout=dest,check=True,cwd=ROOT)
    rows=json.loads(samples.read_text());print('Labeled wide-stop candidates',len(rows),flush=True)
    folds=[];last_year=datetime.fromtimestamp(end/1000,timezone.utc).year
    for year in range(2024,last_year+1):
        # Previously evaluated calendar years are preserved, never retuned.
        old=next((f for f in previous.get('folds',[]) if f['year']==year),None)
        if old and old.get('completeYear'):folds.append(old);continue
        if old:
            # A later monthly run evaluates only newly available signal dates.
            evaluation_after=old['evaluationEnd']
        else:evaluation_after=0
        training,validation,test=partition(rows,year)
        test=[r for r in test if r['at']>evaluation_after]
        if len(training)<100 or len(validation)<30 or len(test)<20:
            if old:folds.append(old)
            continue
        x=np.array([r['x'] for r in training]);y=np.array([r['y'] for r in training])
        xv=np.array([r['x'] for r in validation]);yv=np.array([r['y'] for r in validation])
        xt=np.array([r['x'] for r in test]);yt=np.array([r['y'] for r in test])
        nn=make_pipeline(StandardScaler(),MLPClassifier(hidden_layer_sizes=(16,8),alpha=1.,solver='lbfgs',max_iter=1000,random_state=42))
        linear=make_pipeline(StandardScaler(),LogisticRegression(C=1.,max_iter=1000,random_state=42))
        with warnings.catch_warnings(record=True) as caught:nn.fit(x,y);linear.fit(x,y)
        choices=[];pv=nn.predict_proba(xv)[:,1]
        for threshold in (.5,.6,.7):
            chosen=[r for r,p in zip(validation,pv) if p>=threshold]
            choices.append({'threshold':threshold,'accepted':len(chosen),'netR':sum(r['netR'] for r in chosen)})
        eligible=[c for c in choices if c['accepted']>=30]
        selected=max(eligible,key=lambda c:(c['netR'],-c['threshold'])) if eligible else choices[0]
        scores=nn.predict_proba(xt)[:,1];base=linear.predict_proba(xt)[:,1]
        start=min(r['at'] for r in test);finish=max(r['labelEnd'] for r in test)
        request={'marketPath':str(market),'profile':'wideRecovery','start':start,'end':finish,'threshold':selected['threshold'],
                 'rows':[dict(r,score=float(p)) for r,p in zip(test,scores)]}
        accounts=json.loads(subprocess.check_output(['node',str(ROOT/'scripts/evaluate_pattern_research.cjs')],input=json.dumps(request).encode(),cwd=ROOT))
        result={'year':year,'evaluationStart':start,'evaluationEnd':finish,'completeYear':end>=stamp(year+1)-1,
                'trainingStart':min(r['at'] for r in training),'trainingEnd':max(r['labelEnd'] for r in training),
                'validationStart':min(r['at'] for r in validation),'validationEnd':max(r['labelEnd'] for r in validation),
                'counts':{'train':len(training),'validation':len(validation),'test':len(test)},'threshold':selected['threshold'],
                'validationOptions':choices,'warnings':[str(w.message) for w in caught],
                'neuralBrier':float(brier_score_loss(yt,scores)),'linearBrier':float(brier_score_loss(yt,base)),
                'constantBrier':float(brier_score_loss(yt,np.full(len(yt),float(y.mean())))),'accounts':accounts,
                'incrementalAfter':evaluation_after,'previousSegments':old.get('previousSegments',[])+[{k:v for k,v in old.items() if k!='previousSegments'}] if old else []}
        folds.append(result)
        scaler,model=nn.steps[0][1],nn.steps[1][1]
        model_file=f'{now}-{year}-model.json'
        (folder/model_file).write_text(json.dumps({'version':VERSION,'features':FEATURES,'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),'coefs':[v.tolist() for v in model.coefs_],'intercepts':[v.tolist() for v in model.intercepts_],'threshold':selected['threshold']}))
        result['modelFile']=model_file
        print('Completed evaluation',year,result['counts'],accounts,flush=True)
    if not folds:raise ValueError('No valid multi-year evaluation partitions')
    reasons=[]
    if any(f['accounts']['neuralFilter']['trades']<100 for f in folds):reasons.append('평가 구간별 신경망 종료 거래 100건 미달')
    if any(f['accounts']['neuralFilter']['return']<=0 for f in folds):reasons.append('모든 평가 구간에서 비용 차감 수익 양수를 달성하지 못함')
    if any(f['neuralBrier']>=min(f['linearBrier'],f['constantBrier']) for f in folds):reasons.append('일부 구간에서 단순 모델보다 예측 오차가 큼')
    if any(f['warnings'] for f in folds):reasons.append('일부 신경망 학습에서 수렴 경고 발생')
    if any(f['accounts']['neuralFilter']['maxDrawdown']>f['accounts']['rules']['maxDrawdown'] for f in folds):reasons.append('일부 구간에서 규칙 계좌보다 최대 낙폭이 큼')
    if any(f['accounts']['neuralFilter']['return']<=f['accounts']['rules']['return'] for f in folds):reasons.append('일부 구간에서 규칙 계좌보다 수익이 낮음')
    if any(v['missingBars'] or v['invalidRows'] for v in manifest['coverage'].values()):reasons.append('원자료 일부 봉 누락·제외: 기간별 자료 한계 확인 필요')
    report={'version':VERSION,'generatedAt':now,'status':'검증 보류' if reasons else '후속 모의 평가 후보','deployed':False,
            'dataEnd':end,'coverage':manifest['coverage'],'archives':len(manifest['files']),'sourceHash':source_hash,
            'sampleHash':hashlib.sha256(samples.read_bytes()).hexdigest(),'samples':len(rows),'folds':folds,'reasons':reasons,
            'model':'MLP 16 → 8 · 확장 학습','venue':'Binance USD-M 공개 선물 기록',
            'notes':['코인 선물의 수십 년 기록은 존재하지 않습니다. 실제 월별 자료의 시작일부터 학습합니다.',
                     '2020년부터 학습 범위를 늘리고 직전 1년으로 선택한 뒤 다음 연도로 평가합니다. 경계는 32봉 추가 분리합니다.',
                     '각 평가 구간은 별도 $10,000 계좌이며 수익률을 더하거나 연결한 하나의 실적이 아닙니다.',
                     '장기 기록은 Binance, 진행 계좌는 Hyperliquid입니다. 거래소·유동성 차이 때문에 직접 이전 성능이 보장되지 않습니다.',
                     '과거 전체 시세를 탐색한 연구로, 발표 이후 모의운용 성적과 구분합니다. 최적 원칙이나 검증된 적중률을 의미하지 않습니다.',
                     '수수료 0.045%·슬리피지 0.02% 편도 고정, 실제 기록된 펀딩 정산 간격 적용. 역사적 거래소 수수료 등급·정확한 청산 엔진은 생략합니다.',
                     '이전 연구·모델은 보존하며 새 월별 자료가 있을 때 새 평가 구간을 추가합니다. 검증되지 않은 신경망은 운용에 적용하지 않습니다.']}
    (folder/f'{now}-manifest.json').write_text(json.dumps(manifest))
    report['manifestFile']=f'{now}-manifest.json'
    (folder/f'{now}-report.json').write_text(json.dumps(report,ensure_ascii=False));latest.write_text(json.dumps(report,ensure_ascii=False))
    print(json.dumps({'status':report['status'],'coverage':report['coverage'],'samples':len(rows),'reasons':reasons},ensure_ascii=False),flush=True)

if __name__=='__main__':train()
