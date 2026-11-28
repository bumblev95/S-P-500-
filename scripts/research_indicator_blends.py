"""Exploratory causal blends; does not modify UI, forecasts or trading rules.

Two predeclared hypotheses: convex point combinations, and a downside
classifier gating a downside magnitude expert. Every weight-selection label
must have matured before its new forecast. Revisited history is not live data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn

from research_joint_indicator import (ROOT, LABELS, date_weights, direction_ci,
    label, predict_candidate, score, split_matured, validate_source)

FOLDER = ROOT/'research/joint-indicator/blends'
NAMES = {'noChange': '가격 불변', 'priceOnly': '가격 패턴',
    'joint_logistic': '공동 분포 단독', 'fixed_half': '단순 50:50',
    'causal_error_blend': '과거 오차 최소 조합',
    'causal_joint_blend': '방향·오차 조건 조합',
    'down_soft_mix': '하락 점수 가중 조합',
    'guarded_down_route': '조건 충족 시 하락 후보 전환'}


def matured_forecasts(history, origin):
    return [r for r in history if r['origin'] < origin and r['targetDate'] < origin]


def conditional_down_magnitude(rows):
    """Weighted median of y with weights /y minimizes MAPE within down class."""
    down = [r for r in rows if label(r['y']) == -1]
    if not down:
        raise ValueError('No matured downside magnitude observations')
    actual = np.asarray([r['y'] for r in down], dtype=float)
    weights = date_weights(down) / actual
    order = np.argsort(actual, kind='stable')
    cumulative = np.cumsum(weights[order])
    index = np.searchsorted(cumulative, cumulative[-1]/2, side='left')
    return float(actual[order[index]])


def project_forecast(row, joint, down_value):
    """Future price and target date deliberately absent from prediction inputs."""
    return dict(symbol=row['symbol'], origin=row['origin'], priceOnly=row['priceOnly'],
                noChange=1., specialist=joint['value'],
                downScore=joint['probability'][0], upScore=joint['probability'][2],
                downValue=down_value)


def convex_prediction(features, default, weight):
    a = np.array([r[default] for r in features])
    b = np.array([r['specialist'] for r in features])
    return (1-weight)*a + weight*b


def routed_prediction(features, default, threshold):
    use_down = np.array([r['downScore'] >= threshold and r['downScore'] > r['upScore']
                         for r in features])
    return np.where(use_down, [r['downValue'] for r in features],
                    [r[default] for r in features])


def selection_metrics(rows, forecast):
    actual = np.asarray([r['y'] for r in rows])
    truth, predicted = label(actual), label(forecast)
    weights = date_weights(rows)
    recalls = [float(np.average(predicted[truth == c] == c, weights=weights[truth == c]))
               if np.any(truth == c) else 0. for c in LABELS]
    warnings = predicted == -1
    precision = float(np.average(truth[warnings] == -1, weights=weights[warnings])) \
                if warnings.any() else None
    return dict(mape=float(np.average(abs(forecast/actual-1), weights=weights)),
        returnMae=float(np.average(abs(forecast-actual), weights=weights)),
        balancedAccuracy=float(np.mean(recalls)), upRecall=recalls[2],
        downRecall=recalls[0], downPrecision=precision, downWarnings=int(warnings.sum()),
        downPrevalence=float(np.average(truth == -1, weights=weights)))


def guard_ok(metrics, default_metrics, protocol):
    guard = protocol['calibrationGuard']
    return (metrics['mape'] <= guard['maxErrorRatio'] * min(m['mape'] for m in default_metrics)
        and metrics['returnMae'] <= guard['maxErrorRatio'] * min(m['returnMae'] for m in default_metrics)
        and metrics['upRecall'] >= guard['minimumUpRecall']
        and metrics['downRecall'] >= guard['minimumDownRecall']
        and metrics['downWarnings'] >= guard['minimumDownWarnings']
        and metrics['downPrecision'] is not None
        and metrics['downPrecision'] >= metrics['downPrevalence'] + guard['minimumDownPrecisionLift'])


def choose_settings(history, origin, protocol):
    past = matured_forecasts(history, origin)
    info = dict(rows=len(past), dates=len({r['origin'] for r in past}),
        targetThrough=max((r['targetDate'] for r in past), default=None),
        lastOrigin=max((r['origin'] for r in past), default=None))
    fallback = dict(default='priceOnly', weight=.5, status='insufficient_dates_fixed_half')
    if info['dates'] < protocol['minimumBlendDates']:
        return dict(error=fallback.copy(), joint=fallback.copy(),
                    route=dict(status='insufficient_dates_use_error_blend'), history=info)
    features = [r['features'] for r in past]
    defaults = [selection_metrics(past, np.array([r[k] for r in features]))
                for k in protocol['defaults']]
    candidates = []
    # Explicit deterministic tie order: noChange before priceOnly, smaller weight first.
    for default in ('noChange', 'priceOnly'):
        for weight in protocol['blendWeights']:
            metrics = selection_metrics(past, convex_prediction(features, default, weight))
            candidates.append(dict(default=default, weight=weight, metrics=metrics))
    best = min(candidates, key=lambda c: c['metrics']['mape'])
    error = dict(best, status='selected_on_matured_oos')
    feasible = [c for c in candidates if guard_ok(c['metrics'], defaults, protocol)]
    joint = dict(min(feasible, key=lambda c: (-c['metrics']['balancedAccuracy'],
                    c['metrics']['mape'], c['metrics']['returnMae'])), status='selected_on_matured_oos') \
            if feasible else dict(error, status='infeasible_guard_use_error_blend')
    routed = []
    for default in ('noChange', 'priceOnly'):
        for threshold in protocol['routeThresholds']:
            metrics = selection_metrics(past, routed_prediction(features, default, threshold))
            if guard_ok(metrics, defaults, protocol):
                routed.append(dict(default=default, threshold=threshold, metrics=metrics))
    route = dict(min(routed, key=lambda c: (-c['metrics']['balancedAccuracy'],
                    c['metrics']['mape'], c['metrics']['returnMae'])), status='selected_on_matured_oos') \
            if routed else dict(status='infeasible_guard_use_error_blend')
    return dict(error=error, joint=joint, route=route, history=info)


def predict_blends(features, settings):
    error, joint, route = (settings[k] for k in ('error', 'joint', 'route'))
    values = dict(fixed_half=convex_prediction(features, 'priceOnly', .5),
        causal_error_blend=convex_prediction(features, error['default'], error['weight']),
        causal_joint_blend=convex_prediction(features, joint['default'], joint['weight']),
        down_soft_mix=np.array([r['downScore']*r['downValue'] +
                               (1-r['downScore'])*r['priceOnly'] for r in features]))
    values['guarded_down_route'] = routed_prediction(features, route['default'], route['threshold']) \
        if route['status'] == 'selected_on_matured_oos' else values['causal_error_blend'].copy()
    if any(not np.isfinite(v).all() or np.any(v <= 0) for v in values.values()):
        raise ValueError('Invalid combined forecast')
    return {name: [dict(value=float(v), direction=int(label(v))) for v in forecasts]
            for name, forecasts in values.items()}


def extended_score(rows, name):
    metrics = score(rows, name)
    actual = np.array([r['y'] for r in rows])
    forecast = np.array([r['methods'][name]['value'] for r in rows])
    direction = np.array([r['methods'][name]['direction'] for r in rows])
    return_error = abs(forecast-actual)
    for day, stats in metrics['byDate'].items():
        mask = np.array([r['origin'] == day for r in rows])
        stats['returnMae'] = float(return_error[mask].mean())
    actual_non_down = label(actual) != -1
    warnings = direction == -1
    metrics.update(returnMae=float(return_error.mean()),
        dateMeanReturnMae=float(np.mean([m['returnMae'] for m in metrics['byDate'].values()])),
        p90ReturnError=float(np.quantile(return_error, .9)),
        downWarnings=int(warnings.sum()), falseDownWarnings=int(np.sum(warnings & actual_non_down)),
        falseDownWarningRate=float(np.mean(warnings[actual_non_down])) if actual_non_down.any() else None,
        pointDirectionAgreement=float(np.mean(direction == label(forecast))))
    return metrics


def blend_gates(m, price, unchanged, protocol):
    g = protocol['gate']
    wins = np.mean([v['mape'] < min(price['byDate'][d]['mape'], unchanged['byDate'][d]['mape'])
                    for d, v in m['byDate'].items()])
    return dict(enoughDates=m['dates'] >= g['minimumEvaluationDates'],
        priceError=m['dateMeanMape'] <= (1-g['priceErrorImprovement'])*
            min(price['dateMeanMape'], unchanged['dateMeanMape']),
        returnError=m['dateMeanReturnMae'] <= (1-g['priceErrorImprovement'])*
            min(price['dateMeanReturnMae'], unchanged['dateMeanReturnMae']),
        tail=m['p90Mape'] <= min(price['p90Mape'], unchanged['p90Mape']),
        returnTail=m['p90ReturnError'] <= min(price['p90ReturnError'], unchanged['p90ReturnError']),
        dateConsistency=bool(wins >= g['minimumDateWinRate']),
        direction=m['directionAccuracy'] > max(m['alwaysUpAccuracy'], price['directionAccuracy']),
        returnDirection=m['returnDirectionAccuracy'] > max(m['alwaysUpAccuracy'], price['returnDirectionAccuracy']),
        balancedDirection=m['balancedDirectionAccuracy'] > max(1/3, price['balancedDirectionAccuracy']),
        upRecall=m['upRecall'] is not None and m['upRecall'] >= g['minimumUpRecall'],
        downRecall=m['downRecall'] is not None and m['downRecall'] >= g['minimumDownRecall'],
        downPrecision=m['downPrecision'] is not None and m['downPrecision'] >=
            m['downPrevalence'] + g['minimumDownPrecisionLift'],
        directionEvidence=direction_ci(m)[0] > 0, prospective=False)


def diagnostics(rows):
    """Future outcomes are diagnostics only; best endpoints are not a convex bound."""
    y = np.array([r['y'] for r in rows])
    price = np.array([r['methods']['priceOnly']['value'] for r in rows])
    joint = np.array([r['methods']['joint_logistic']['value'] for r in rows])
    weights = date_weights(rows)
    ea, eb = np.log(price/y), np.log(joint/y)
    ea -= np.average(ea, weights=weights)
    eb -= np.average(eb, weights=weights)
    correlation = np.average(ea*eb, weights=weights) / np.sqrt(
        np.average(ea**2, weights=weights)*np.average(eb**2, weights=weights))
    best_error = np.minimum(abs(price/y-1), abs(joint/y-1))
    ref_probability = np.array([r['methods']['joint_logistic']['probability'][0] for r in rows])
    truth_down = label(y) == -1
    bins = []
    for low, high in zip(np.arange(0, 1, .1), np.arange(.1, 1.1, .1)):
        mask = (ref_probability >= low) & (ref_probability < high if high < 1 else ref_probability <= 1)
        if mask.any():
            bins.append(dict(low=float(low), high=float(high), n=int(mask.sum()),
                meanScore=float(np.average(ref_probability[mask], weights=weights[mask])),
                realizedDownRate=float(np.average(truth_down[mask], weights=weights[mask]))))
    return dict(logErrorCorrelation=float(correlation),
        specialistHasLowerPriceError=float(np.average(abs(joint/y-1) < abs(price/y-1), weights=weights)),
        directionDisagreement=float(np.average(label(price) != label(joint), weights=weights)),
        impossibleOracleEndpointMape=float(np.average(best_error, weights=weights)),
        oracleIsExecutable=False, downsideScoreBins=bins,
        probabilityNote='Reference classifier scores only; numerical combinations have no probability claim.')


def validate_issuers(source):
    members = json.loads((ROOT/'research/universe.json').read_text())['members']
    for horizon in ('126', '252'):
        seen = set()
        for row in source['stocks'][horizon]['outcomes']:
            cik = members[row['symbol']]['cik']
            key = (row['origin'], cik)
            if key in seen:
                raise ValueError('Duplicate issuer/date in outcome rows')
            seen.add(key)


def evaluate(source, protocol, joint_protocol):
    result = {}
    first_results = json.loads((ROOT/'research/joint-indicator/results.json').read_text())
    for h in protocol['horizons']:
        rows = source['stocks'][str(h)]['outcomes']
        origins = sorted({r['origin'] for r in rows})
        start = origins[len(origins)//2]
        evaluated, history, folds = [], [], []
        for day in origins:
            split = split_matured(rows, day, joint_protocol)
            if split is None:
                folds.append(dict(origin=day, status='insufficient_joint_history'))
                continue
            fit, calibration, matured = split
            test = [r for r in rows if r['origin'] == day]
            print(h, day, 'joint fit', len(fit), 'test', len(test), flush=True)
            joint = predict_candidate('joint_logistic', fit, calibration, matured, test)
            down_value = conditional_down_magnitude(matured)
            features = [project_forecast(row, p, down_value) for row, p in zip(test, joint)]
            settings = choose_settings(history, day, protocol)
            predictions = predict_blends(features, settings)
            for i, row in enumerate(test):
                methods = {k: dict(value=float(row[k]), direction=int(label(row[k])))
                           for k in ('priceOnly', 'noChange')}
                methods['joint_logistic'] = joint[i]
                methods.update({k: v[i] for k, v in predictions.items()})
                historical = dict(symbol=row['symbol'], origin=day, targetDate=row['targetDate'],
                    y=row['y'], regime=row['regime'], features=features[i], methods=methods)
                history.append(historical)
                if day >= start:
                    evaluated.append(historical)
            folds.append(dict(origin=day, status='evaluated' if day >= start else 'warmup',
                fitTargetThrough=max(r['targetDate'] for r in fit),
                calibrationStart=min(r['origin'] for r in calibration),
                calibrationTargetThrough=max(r['targetDate'] for r in calibration),
                shapeTargetThrough=max(r['targetDate'] for r in matured), testRows=len(test),
                conditionalDownValue=down_value, settings=settings))
        if not evaluated:
            result[str(h)] = dict(status='insufficient', folds=folds)
            continue
        metrics = {name: extended_score(evaluated, name) for name in NAMES}
        if protocol['sourceHash'] == first_results['sourceHash']:
            for name in ('noChange', 'priceOnly', 'joint_logistic'):
                previous = first_results['horizons'][str(h)]['evaluation'][name]
                for key in ('n', 'dates', 'dateMeanMape', 'directionAccuracy', 'downRecall'):
                    if not np.isclose(metrics[name][key], previous[key], atol=1e-12, rtol=0):
                        raise ValueError('Paired sample/reference differs from joint v1: '+key)
        checks = {name: blend_gates(metrics[name], metrics['priceOnly'], metrics['noChange'], protocol)
                  for name in protocol['candidates']}
        regimes = {regime: {name: extended_score([r for r in evaluated if r['regime'] == regime], name)
                   for name in NAMES} for regime in sorted({r['regime'] for r in evaluated})}
        result[str(h)] = dict(status='research', evaluationStart=start,
            evaluatedDates=sorted({r['origin'] for r in evaluated}), evaluation=metrics,
            regimes=regimes, checks=checks, folds=folds, diagnostics=diagnostics(evaluated),
            historicalPassed={name: all(v for k, v in c.items() if k != 'prospective') for name, c in checks.items()},
            passed={name: all(c.values()) for name, c in checks.items()}, selected=None,
            settingsStatus={key: dict(Counter(f['settings'][key]['status'] for f in folds
                if f['status'] == 'evaluated')) for key in ('error', 'joint', 'route')},
            pairedRowsHash=hashlib.sha256(json.dumps(evaluated, sort_keys=True).encode()).hexdigest(),
            directionImprovementCI={name: direction_ci(metrics[name]) for name in protocol['candidates']})
    return result


def report(result):
    lines = ['# 하락 포착 후보와 낮은 오차 후보의 결합 연구', '',
        f"생성: {result['generatedAt']} · 프로토콜 등록: {result['registeredAt']}", '',
        '웹 화면·서비스 AI·순위·운용 정책을 변경하지 않았습니다. 앞서 검토한 동일 과거 자료를 다시 사용한 탐색 결과입니다. 후보도 앞선 실험을 보고 정했으므로 새로운 미검토 외부표본이나 실전 검증이 아닙니다.', '',
        '가설 A는 예측값 평균·과거 오차 최소 조합·방향을 고려한 조합, 가설 B는 하락 점수로 비중 조절·과거 성적 조건을 만족할 때만 하락 후보로 전환하는 조합입니다. 모든 비중과 전환 문턱은 해당 기준일 이전에 결과가 확정된 외부표본 예측으로만 정합니다.', '',
        '최종 방향은 결합한 수익률 자체의 부호(±2% 중립)를 평가합니다. 분류 점수에 맞춰 수익률의 부호를 덮어쓰지 않습니다. 하락 전문가의 값은 과거 실제 하락 표본에서 학습한 조건부 수익률입니다.', '']
    fmt = lambda x: '—' if x is None else f'{x*100:.2f}'
    for h, q in result['horizons'].items():
        lines += [f"## {'6개월' if h == '126' else '1년'}", '']
        if q['status'] == 'insufficient':
            lines += ['자료 부족.', '']
            continue
        price = q['evaluation']['priceOnly']
        lines += [f"동일 표본 {price['n']}개 · {price['dates']}개 기준일. 항상 상승 적중률 {fmt(price['alwaysUpAccuracy'])}%.", '',
            '| 조합 | 가격 MAPE % | 수익률 MAE %p | 방향 적중 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % | 잘못된 하락 경고율 % |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
        for name, m in q['evaluation'].items():
            lines.append('| '+NAMES[name]+' | '+' | '.join(fmt(m[k]) for k in
                ('dateMeanMape', 'dateMeanReturnMae', 'directionAccuracy', 'upRecall',
                 'downRecall', 'downPrecision', 'falseDownWarningRate'))+' |')
        lines += ['', 'MAPE는 실제 미래 가격 대비 상대 오차입니다. 수익률 MAE는 예측 수익률과 실제 수익률의 차이(%p)입니다. 두 오차는 기준일별 평균을 동일 가중합니다. 방향 포착·경고 지표는 같은 전체 표본 기준입니다. 잘못된 하락 경고율은 실제 하락이 아닌 표본 중 하락으로 잘못 경고한 비율입니다.', '',
            '공동 분포 단독의 방향은 클래스 점수 argmax이며 수익률 중앙값의 부호와 다를 수 있습니다. 결합 후보는 최종 값의 부호로 평가하므로 단독 방향 수치만 비교하면 안 됩니다. 단독 수익률 부호 적중률: '+fmt(q['evaluation']['joint_logistic']['returnDirectionAccuracy'])+'%.', '']
        d = q['diagnostics']
        lines += [f"가격 패턴과 공동 분포의 로그 오차 상관 {d['logErrorCorrelation']:.3f}; 공동 분포가 더 낮은 가격 오차를 낸 비중 {fmt(d['specialistHasLowerPriceError'])}%.", '',
            f"미래 정답을 알고 매 표본 더 좋은 둘 중 하나를 고른 비현실적 참고 오차 {fmt(d['impossibleOracleEndpointMape'])}%. 이는 두 끝점 중 선택하는 미래 정보 기반 참고값이며, 중간 비중까지 허용한 최저 오차 경계나 실행 가능한 전략이 아닙니다.", '']
        for name, c in q['checks'].items():
            failed = ', '.join(k for k, v in c.items() if not v)
            lines.append(f"- {NAMES[name]}: {'과거 조건 통과' if q['historicalPassed'][name] else '과거 조건 미통과'}; 미통과 `{failed}`.")
        lines += ['', '과거 성적 조건이 안 맞을 때의 대체 경로도 제외하지 않고 전체 표본에 포함했습니다.', '']
        for k, statuses in q['settingsStatus'].items():
            lines.append(f'- {k}: '+', '.join(f'{s} {n}개 기준일' for s, n in statuses.items()))
        lines += ['', f"참고 분류기의 Brier {q['evaluation']['joint_logistic']['brier']:.4f}, 당시 이전 결과 비율 기준 {q['evaluation']['joint_logistic']['priorBrier']:.4f}. 숫자 결합 후보에 이 분류기의 확률을 그대로 붙이지 않았습니다. 확률 신뢰도는 results.json의 하락 점수 구간별 실제 하락 비율도 확인해야 합니다.", '']
    lines += ['## 해석과 후속 연구', '',
        '- 단순 평균은 오차를 줄이면서도 하락 신호를 약화시킬 수 있고, 하락 점수만 강조하면 잘못된 경고가 늘 수 있습니다. 둘 중 한 항목만 좋아진 결과는 전체 개선으로 인정하지 않습니다.',
        '- 현재 기업 구성으로 과거를 평가한 생존 편향, 수정 가격·공시 자료의 한계, 적은 시장 기준일과 기준일 간 상관이 남아 있습니다. 동일 기준일에는 CIK당 한 표본만 사용한 입력임을 검사했습니다.',
        '- 이 연구의 가격 패턴 기준은 웹 서비스 모델과 다릅니다. 이번 결과로 APP 또는 현재 매도 Top 3를 정당화하거나 서비스 AI보다 우수하다고 주장하지 않습니다.',
        '- 조합 방법·그리드·조건을 결과 확인 후 바꾸지 않았으며 후보 선택·자동 승격은 없습니다. 미래 발행 후 별도 관측이 필요합니다.',
        '- 다음 단계는 오류가 덜 겹치는 시장/종목 고유 강도 입력을 보강하고, 조건별 수익률 크기를 학습하는 조합을 별도 프로토콜에서 비교합니다. 기간 중 낙폭 포착은 6개월·1년 종료 수익률과 별도 평가합니다.', '',
        '## 근거 자료', '',
        '- [예측 결합의 방법과 한계: Wang, Hyndman, Li, Kang](https://arxiv.org/abs/2205.04216)',
        '- [외부표본 예측을 이용한 스태킹과 과적합 위험](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.StackingRegressor.html)',
        '- [Adaptive Mixtures of Local Experts](https://www.cs.toronto.edu/~hinton/absps/jjnh91.pdf)',
        '- [확률 교정과 신뢰도 점검](https://scikit-learn.org/stable/modules/calibration.html)', '',
        '위 자료는 결합 방법의 연구 근거입니다. 이 종목·기간에서의 성능 보장은 아닙니다.', '',
        '재현: `python scripts/research_indicator_blends.py` · 검사: `python scripts/test_indicator_blends.py`', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT/'research/environment.json')
    parser.add_argument('--output', type=Path, default=FOLDER)
    args = parser.parse_args()
    protocol_path = FOLDER/'PROTOCOL.json'
    protocol = json.loads(protocol_path.read_text())
    joint_path = ROOT/'research/joint-indicator/PROTOCOL.json'
    joint_protocol = json.loads(joint_path.read_text())
    raw = args.source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != protocol['sourceHash'] or \
       hashlib.sha256(joint_path.read_bytes()).hexdigest() != protocol['jointProtocolHash']:
        raise ValueError('Inputs differ from registered protocol; register a new experiment')
    source = json.loads(raw)
    validate_source(source, protocol)
    validate_issuers(source)
    result = dict(version=protocol['version'], generatedAt=datetime.now(timezone.utc).isoformat(),
        registeredAt=protocol['registeredAt'], sourceCommit=protocol['sourceCommit'],
        parentResearchCommit=protocol['parentResearchCommit'], sourceModel=source['model'],
        sourceGeneratedAt=source['generatedAt'], sourceHash=protocol['sourceHash'],
        protocolHash=hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        codeHash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        jointCodeHash=hashlib.sha256((ROOT/'scripts/research_joint_indicator.py').read_bytes()).hexdigest(),
        universeHash=hashlib.sha256((ROOT/'research/universe.json').read_bytes()).hexdigest(),
        sklearnVersion=sklearn.__version__, historicalHoldoutRevisited=True,
        numericalBlendHasNoProbabilityClaim=True, uiChanged=False, liveForecastChanged=False,
        selection='none', horizons=evaluate(source, protocol, joint_protocol))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    (args.output/'RESULTS.md').write_text(report(result))
    print('Blend research completed; no live changes or selected candidate.', flush=True)


if __name__ == '__main__':
    main()
