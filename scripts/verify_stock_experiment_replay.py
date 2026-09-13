"""E3: replay the final historical origin after physically removing future inputs."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from scipy.stats import spearmanr
from build_forecasts import atomic_json
from build_environment_research import records,features,PROXIES
from run_stock_ranking_experiment import fit_predict,NAMES
from audit_stock_experiment_inputs import audit

ROOT=Path(__file__).resolve().parents[1]

def verify(checkpoint,root=ROOT):
    folder=root/'research/experiments/2026-09-13';inputs_check=audit(root)
    baseline=json.loads((root/'research/environment.json').read_text())
    result=json.loads((folder/'e1-ranking.json').read_text());saved=json.loads(Path(checkpoint).read_text())
    archived=saved['outcomes']
    if hashlib.sha256(json.dumps(archived,sort_keys=True,allow_nan=False).encode()).hexdigest()!=result['outcomeHash']:
        raise ValueError('Full forecast artifact does not match the published result hash')
    code_hash=hashlib.sha256((root/'scripts/run_stock_ranking_experiment.py').read_bytes()).hexdigest()
    if code_hash!=result['codeHash']:raise ValueError('E1 code changed before verification')
    comparison=baseline['stocks']['252']['comparison'];max_ic_diff=0.
    for section in ('selection','evaluation'):
        for name in (*NAMES,'momentum'):
            for day,metrics in result['scores'][section][name]['byDate'].items():
                rr=[r for r in archived if r['origin']==day and (section=='evaluation' or r['targetDate']<comparison['evaluationStart'])]
                if len(rr)!=metrics['n']:raise ValueError('Published sample count mismatch')
                measured=float(spearmanr([r[name] for r in rr],[r['y'] for r in rr]).statistic)
                max_ic_diff=max(max_ic_diff,abs(measured-metrics['ic']))
    if max_ic_diff>1e-12:raise ValueError('Published IC cannot be reproduced from forecast rows')
    for r in archived:
        if r['contextThrough']>=r['origin'] or (r['inputThrough'] and r['inputThrough']>=r['origin']):
            raise ValueError('Archived feature information did not precede the forecast origin')
    for f in result['folds']:
        if f['trainTargetThrough']>=f['origin']:raise ValueError('Unmatured training outcome')
    origin=max(r['origin'] for r in archived)
    # Load only data through the replay origin, removing all subsequent prices.
    histories={s:[r for r in json.loads((root/'research/history'/(s.replace('^','INDEX_')+'.json')).read_text())['prices'] if r['date']<=origin]
        for s in set(baseline['stockUniverse'])|set(PROXIES)}
    context={}
    for s in PROXIES:
        f=features(histories[s]);context[s]=dict(features=f,dates=np.array(sorted(f)))
    inputs=json.loads((root/'research/inputs.json').read_text())
    for stock in inputs.get('stocks',{}).values():stock['rows']=[r for r in stock['rows'] if r['availableDate']<origin]
    inputs['earnings']={s:[r for r in rr if r['availableDate']<origin] for s,rr in json.loads((root/'research/earnings.json').read_text())['issuers'].items()}
    members=json.loads((root/'research/universe.json').read_text())['members']
    inputs['symbolCIKs']={s:v['cik'] for s,v in members.items()}
    rows,latest=records({s:histories[s] for s in baseline['stockUniverse']},context,252,'stocks',inputs)
    expected=[r for r in archived if r['origin']==origin]
    def vector(r):return r['w']+[float(r['regime'].startswith('하락')),float('고변동' in r['regime'])]
    x=np.array([vector(r) for r in rows]);test=np.array([vector(latest[r['symbol']]) for r in expected])
    if any(latest[r['symbol']]['origin']!=origin for r in expected):raise ValueError('Replay origin shifted')
    spy={r['date']:r['close'] for r in histories['SPY']}
    absolute=np.log([r['y'] for r in rows]);market=np.log([spy[r['targetDate']]/spy[r['origin']] for r in rows])
    predictions,status=fit_predict(x,np.column_stack([absolute,absolute-market]),rows,test,origin)
    difference={name:float(np.max(np.abs(predictions[name]-[r[name] for r in expected]))) for name in NAMES}
    if max(difference.values())>1e-8:raise ValueError('Removing future inputs changed the historical predictions: '+str(difference))
    issued=json.loads((folder/'e1-issued.json').read_text())
    if issued['issuedAt'][:10]<=issued['asOf'] or issued['training']['trainTargetThrough']>=issued['asOf']:
        raise ValueError('Invalid prospective issuance chronology')
    final=dict(experiment='stock-validation-e3-replay-v1',completedAt=datetime.now(timezone.utc).isoformat(),
        passed=True,fullForecastRows=len(archived),maxPublishedIcDifference=max_ic_diff,
        replayOrigin=origin,replayRows=len(expected),replayTraining=status,maxPredictionDifference=difference,
        truncatedInputs=['All prices after replay origin','All annual and original quarterly filings on or after replay origin'],
        inputChecks=dict(priceFiles=inputs_check['matchedPriceFiles'],matchedTargets=inputs_check['matchedTargets']),
        prospective=dict(issuedAt=issued['issuedAt'],asOf=issued['asOf'],issuers=len(issued['predictions']),
            status='awaiting_252_trading_day_outcomes',fileHash=hashlib.sha256((folder/'e1-issued.json').read_bytes()).hexdigest()),
        productionPromoted=False,limitations='This verifies the recorded implementation; it does not remove survivorship bias or establish future predictive accuracy.')
    atomic_json(folder/'e3-verification.json',final)
    lines=['# E3: 결과 재현 및 미래 정보 제거 검증','',
        f"전체 예측 {len(archived)}행에서 보고된 IC 재계산: 일치.",
        f"{origin} 이후 가격과 공시를 제거하고 {len(expected)}개 종목의 네 모델을 다시 학습했다.",
        f"예측값 최대 차이: {max(difference.values()):.12g}. 허용 오차 1e-8 이내.",
        f"가격 파일 {inputs_check['matchedPriceFiles']}개와 과거 실제 수익률 {inputs_check['matchedTargets']}개: 원래 자료와 일치.",
        f"{issued['issuedAt']}에 {len(issued['predictions'])}개 기업의 연구용 점수 발행. 미래 성적은 아직 미확정.",
        '현재 구성 종목 사용에 따른 생존 편향과 적은 평가 날짜 문제는 이 코드 검사로 해소되지 않는다.']
    (folder/'E3-RESULTS.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines),flush=True)
    return final

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--checkpoint',required=True)
    verify(parser.parse_args().checkpoint)
