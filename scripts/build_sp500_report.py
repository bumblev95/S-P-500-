"""Small, reproducible summary of the completed current-constituent experiment."""
import json
from pathlib import Path
from build_forecasts import atomic_json

ROOT=Path(__file__).resolve().parents[1]
def build(root=ROOT):
    data=json.loads((root/'research/environment.json').read_text())
    coverage=data['universeCoverage'];horizons={}
    for h,v in data['stocks'].items():
        e=v['enrichment'];rows=v['outcomes']
        horizons[h]=dict(matchedRows=e['matchedRows'],matchedIssuers=len(e['matchedBySymbol']),
            evaluation={k:{a:b for a,b in m.items() if a not in ('byDate','logByDate')} for k,m in e['evaluation'].items()},
            horizonSpecific=v.get('horizonSpecific'),
            alwaysUpDirectionAccuracy=e['alwaysUpDirectionAccuracy'],directionCounts=e['directionCounts'],bySector=e.get('bySector',{}),
            firstOrigin=min((r['origin'] for r in rows),default=None),lastOrigin=max((r['origin'] for r in rows),default=None),
            evaluationDates=v['comparison'].get('evaluationDates',[]),trainingStatus=v['trainingStatus'])
    summary=dict(model=data['model'],generatedAt=data['generatedAt'],coverage=coverage,horizons=horizons,errors=data['errors'],limitations=data['limitations'])
    atomic_json(root/'research/sp500-summary.json',summary)
    pct=lambda x:'자료 부족' if x is None else f'{x*100:.2f}%'
    sec=coverage.get('sec',{})
    lines=['# S&P 500 실적 학습 비교', '',f"생성: {data['generatedAt']} · 모델: {data['model']}",'',
        f"대상 {coverage['targetIssuers']}개 기업 / {coverage['targetTickers']}개 종목. SEC 유효 재무 이력 {sec.get('usableIssuers',0)}개 기업. 가격 이력 {coverage['priceIssuers']}개 기업 / {coverage['priceTickers']}개 종목.",'',
        '현재 구성 기업을 과거에 대입한 연구입니다. 당시 지수 구성 종목 전체를 복원한 검증은 아니며 생존 편향이 남습니다. 같은 회사의 여러 종류 주식은 대표 1종목만 학습·평가하고, 자료가 있는 모든 종류 주식의 전망은 계산합니다. 가격·시장 정보 기준 연구 모델과 실적 추가 모델을 같은 기업·날짜로 비교하며, 메인 서비스 모델과의 직접 성능 비교가 아닙니다.','',
        '연간 SEC 표준 US-GAAP 수치와 NVDA·MSFT 공식 분기 발표를 사용합니다. 발표 다음 날부터 입력하며, 과거 분기별 서프라이즈·뉴스 해석은 포함하지 않습니다. 재무 지표를 처리할 수 없는 기업은 누락 목록에 남깁니다.','',
        '| 기간 | 분리 모델 | 분리 모델 가격 오차 | 분리 모델 방향 적중 | 분리 모델 하락 포착 | 예측 상승 / 중립 / 하락 |',
        '|---|---|---:|---:|---:|---:|']
    for h,v in horizons.items():
        separated=v.get('horizonSpecific') or {};e=separated.get('evaluation') or {};counts=separated.get('directionCounts') or {}
        lines.append(f"| {h}거래일 | {(separated.get('profile') or {}).get('name','자료 부족')} | {pct(e.get('mape'))} | {pct(e.get('directionAccuracy'))} | {pct(e.get('downRecall'))} | {counts.get('up',0)} / {counts.get('flat',0)} / {counts.get('down',0)} |")
    lines += ['', '21·84·252거래일 모델은 입력 범위, 모델 복잡도와 방향 분류기를 서로 공유하지 않습니다. 21일은 가격·시장환경 중심, 84일과 252일은 발표일이 확인된 SEC·실적 변수도 사용합니다. 방향은 상승·중립(±2%)·하락의 세 범주입니다. 하락 포착률은 실제 하락한 표본 가운데 하락으로 예측한 비율입니다. 표본 수는 독립된 시장 상황의 수가 아니며, 이번 결과만으로 기본 모델을 자동 교체하지 않습니다.', '',
        '## 누락과 출처','',f"종목 목록: [{coverage['source']}]({coverage['source']}) · 확인 {coverage['retrievedAt']}",'',
        'SEC 유효 이력 미확보: '+(', '.join(sec.get('missingSymbols',[])) or '없음'),'',
        '가격 자료 부족: '+(', '.join(coverage.get('missingPrices',{})) or '없음'),'',
        '수집 상태와 업종별 비교는 [요약 데이터](sp500-summary.json), 전체 시점별 결과는 [연구 데이터](environment.json)에서 확인할 수 있습니다.']
    (root/'research/SP500-LEARNING.md').write_text('\n'.join(lines)+'\n')
    return summary

if __name__=='__main__':build()
