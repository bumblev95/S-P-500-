"""Causal robust-loss and conditional-magnitude research, never live deployment.

The registered design tests four candidates and a matched squared-error
control. Uses existing historical OOS predictions as features, so results
remain exploratory even with strict causal fits at each origin.
"""
from __future__ import annotations

import os
os.environ.setdefault('OMP_NUM_THREADS', '2')
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from research_joint_indicator import (ROOT, LABELS, date_weights, label, matrix,
    predict_candidate, split_matured, validate_source)
from research_indicator_blends import blend_gates, extended_score, validate_issuers

FOLDER = ROOT/'research/joint-indicator/conditional'
NAMES = {'noChange': '가격 불변', 'priceOnly': '가격 패턴',
    'joint_logistic': '기존 공동 분포', 'direct_squared': '동일 구조 제곱오차 대조군',
    'direct_return_mae': '수익률 절대오차 직접 학습',
    'direct_price_mape': '가격 비율오차 직접 학습',
    'conditional_return_mae': '방향별 크기 · 수익률 오차',
    'conditional_price_mape': '방향별 크기 · 가격 오차'}


def mature_magnitude_rows(rows, origin):
    return [r for r in rows if r['origin'] < origin and r['targetDate'] < origin]


def loss_weights(rows, objective):
    weights = date_weights(rows)
    if objective == 'mape':
        weights = weights / np.array([r['y'] for r in rows])
    elif objective not in ('mae', 'squared'):
        raise ValueError('Unknown magnitude objective')
    if not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError('Invalid magnitude training weights')
    return weights * len(weights) / weights.sum()


def weighted_median(values, weights):
    values, weights = np.asarray(values), np.asarray(weights)
    if len(values) == 0 or np.any(weights < 0) or not weights.sum() > 0:
        raise ValueError('Empty or invalid weighted-median support')
    order = np.argsort(values, kind='stable')
    masses = np.cumsum(weights[order])
    return float(values[order[np.searchsorted(masses, masses[-1]/2, side='left')]])


def historical_clip(forecast, training):
    actual = np.array([r['y'] for r in training])
    raw = np.asarray(forecast)
    if not np.isfinite(raw).all() or np.any(actual <= 0):
        raise ValueError('Invalid prediction or historical support')
    clipped = np.clip(raw, actual.min(), actual.max())
    return clipped, dict(lower=float(actual.min()), upper=float(actual.max()),
                         clipped=int(np.sum(raw != clipped)))


def train_regressor(rows, x_test, objective, protocol):
    model = HistGradientBoostingRegressor(
        loss='squared_error' if objective == 'squared' else 'absolute_error',
        **protocol['regressor'])
    model.fit(matrix(rows), np.array([r['y'] for r in rows]),
              sample_weight=loss_weights(rows, objective))
    return historical_clip(model.predict(x_test), rows)


def conditional_support(rows, x_test, objective, protocol):
    groups = [[r for r in rows if label(r['y']) == c] for c in LABELS]
    if any(len(own) == 0 for own in groups):
        raise ValueError('Missing matured conditional class')
    fallback = any(len(own) < protocol['minimumMagnitudeClassRows'] for own in groups)
    support, bounds = [], []
    for own in groups:
        if fallback:
            point = weighted_median([r['y'] for r in own], loss_weights(own, objective))
            values, info = historical_clip(np.full(len(x_test), point), own)
        else:
            values, info = train_regressor(own, x_test, objective, protocol)
        support.append(values)
        bounds.append(dict(info, rows=len(own), dates=len({r['origin'] for r in own})))
    return np.array(support).T, dict(fallback=fallback, classSupport=bounds)


def loss_optimal_point(support, probability, objective):
    support, probability = np.asarray(support), np.asarray(probability)
    if support.shape != probability.shape or support.shape[1] != 3:
        raise ValueError('Conditional support/probability alignment error')
    if np.any(support <= 0) or not np.isfinite(support).all() or \
       np.any(probability < 0) or not np.isfinite(probability).all() or \
       not np.allclose(probability.sum(axis=1), 1):
        raise ValueError('Invalid conditional support or class probability')
    if not np.all(support[:, 0] < .98) or not np.all((support[:, 1] >= .98) & (support[:, 1] <= 1.02)) \
       or not np.all(support[:, 2] > 1.02):
        raise ValueError('Conditional supports violate class definition')
    if objective == 'mae':
        weights = probability
    elif objective == 'mape':
        weights = probability / support
    else:
        raise ValueError('Unknown conditional decision objective')
    return np.array([weighted_median(values, w) for values, w in zip(support, weights)])


def predict_new_candidates(matured, x_test, probability, protocol):
    numeric, info, support = {}, {}, {}
    for name, objective in (('direct_squared', 'squared'), ('direct_return_mae', 'mae'),
                            ('direct_price_mape', 'mape')):
        numeric[name], info[name] = train_regressor(matured, x_test, objective, protocol)
    for name, objective in (('conditional_return_mae', 'mae'), ('conditional_price_mape', 'mape')):
        support[name], info[name] = conditional_support(matured, x_test, objective, protocol)
        numeric[name] = loss_optimal_point(support[name], probability, objective)
    predictions = {name: [dict(value=float(v), direction=int(label(v))) for v in values]
                   for name, values in numeric.items()}
    return predictions, info, support


def paired_date_intervals(candidate, baseline):
    """Date-grouped exploratory intervals, not independent issuer significance."""
    result = {}
    for key in ('mape', 'returnMae', 'directionAccuracy'):
        diffs = np.array([(baseline['byDate'][d][key] - stats[key]) *
                          (-1 if key == 'directionAccuracy' else 1)
                          for d, stats in candidate['byDate'].items()])
        samples = np.random.default_rng(41).choice(diffs, size=(2000, len(diffs)), replace=True).mean(axis=1)
        result[key] = dict(mean=float(diffs.mean()),
            interval=[float(v) for v in np.quantile(samples, [.025, .975])],
            note='Positive favors candidate; exploratory date bootstrap, dates may be correlated.')
    return result


def evaluate(source, protocol, joint_protocol):
    output = {}
    previous = json.loads((ROOT/'research/joint-indicator/results.json').read_text())
    for horizon in protocol['horizons']:
        rows = source['stocks'][str(horizon)]['outcomes']
        origins = sorted({r['origin'] for r in rows})
        start = origins[len(origins)//2]
        evaluated, folds, diagnostics = [], [], []
        for day in origins:
            if day < start:
                continue
            split = split_matured(rows, day, joint_protocol)
            if split is None:
                raise ValueError('Registered paired evaluation has insufficient causal classifier history')
            fit, calibration, _ = split
            matured = mature_magnitude_rows(rows, day)
            test = [r for r in rows if r['origin'] == day]
            print(horizon, day, 'magnitude history', len(matured), 'test', len(test), flush=True)
            reference = predict_candidate('joint_logistic', fit, calibration, matured, test)
            probability = np.array([p['probability'] for p in reference])
            x_test = matrix(test)
            predictions, info, support = predict_new_candidates(matured, x_test, probability, protocol)
            for i, row in enumerate(test):
                methods = {k: dict(value=float(row[k]), direction=int(label(row[k])))
                           for k in ('noChange', 'priceOnly')}
                methods['joint_logistic'] = reference[i]
                methods.update({k: p[i] for k, p in predictions.items()})
                evaluated.append(dict(symbol=row['symbol'], origin=day, targetDate=row['targetDate'],
                    regime=row['regime'], y=row['y'], methods=methods))
            # Future class is allowed ONLY in this non-executable diagnostic.
            y = np.array([r['y'] for r in test])
            true_index = label(y).astype(int)+1
            oracle = {}
            for name, atoms in support.items():
                with_future_class = atoms[np.arange(len(test)), true_index]
                oracle[name] = dict(returnMae=float(np.mean(abs(with_future_class-y))),
                    mape=float(np.mean(abs(with_future_class/y-1))))
            diagnostics.append(dict(origin=day, n=len(test), magnitudeWithFutureTrueClass=oracle,
                                    executable=False, usedForSelection=False))
            folds.append(dict(origin=day, testRows=len(test), magnitudeRows=len(matured),
                magnitudeDates=len({r['origin'] for r in matured}),
                magnitudeTargetThrough=max(r['targetDate'] for r in matured),
                classifierFitTargetThrough=max(r['targetDate'] for r in fit),
                classifierCalibrationStart=min(r['origin'] for r in calibration),
                classifierCalibrationTargetThrough=max(r['targetDate'] for r in calibration),
                modelInfo=info))
        metrics = {name: extended_score(evaluated, name) for name in NAMES}
        for name in ('noChange', 'priceOnly', 'joint_logistic'):
            old = previous['horizons'][str(horizon)]['evaluation'][name]
            for key in ('n', 'dates', 'dateMeanMape', 'directionAccuracy', 'downRecall'):
                if not np.isclose(metrics[name][key], old[key], rtol=0, atol=1e-12):
                    raise ValueError('Reference or paired sample changed: '+key)
        checks = {name: blend_gates(metrics[name], metrics['priceOnly'], metrics['noChange'], protocol)
                  for name in protocol['candidates']}
        regimes = {regime: {name: extended_score([r for r in evaluated if r['regime'] == regime], name)
                   for name in NAMES} for regime in sorted({r['regime'] for r in evaluated})}
        output[str(horizon)] = dict(evaluationStart=start, evaluatedDates=list(metrics['priceOnly']['byDate']),
            evaluation=metrics, regimes=regimes, checks=checks, folds=folds,
            historicalPassed={name: all(v for k, v in c.items() if k != 'prospective') for name, c in checks.items()},
            passed={name: all(c.values()) for name, c in checks.items()}, selected=None,
            diagnosticTrueClassRouting=diagnostics,
            pairedDateImprovementVsPrice={name: paired_date_intervals(metrics[name], metrics['priceOnly'])
                                         for name in protocol['candidates']},
            pairedRowsHash=hashlib.sha256(json.dumps(evaluated, sort_keys=True).encode()).hexdigest())
    return output


def report(result):
    lines = ['# 수익률 오차 직접 학습과 방향별 크기 연구', '',
        f"생성: {result['generatedAt']} · 등록: {result['registeredAt']}", '',
        '두 가설·네 후보와 동일 구조 제곱오차 대조군을 실행했습니다. 같은 과거 외부표본 자료를 다시 본 탐색이며 새 실전 검증이 아닙니다. 웹 화면·서비스 AI·순위·운용 정책은 변경하지 않았습니다.', '',
        '가설 A는 평균 수익률 차이(MAE) 또는 미래 실제 가격 대비 오차(MAPE)를 직접 줄이도록 학습합니다. 가설 B는 상승·횡보·하락별 크기를 별도로 학습한 뒤 기존 분류 점수와 결합합니다. 숫자 예측의 부호를 덮어쓰거나 상승·하락 개수를 임의로 맞추지 않습니다.', '',
        '기존 외부표본 예측·공시 방향 점수와 알려진 시장 상황을 입력으로 재사용합니다. 새로운 원시 가격·업종 강도·기간 중 낙폭 입력은 추가하지 않았습니다. 따라서 학습 방법을 바꾼 실험이며 새로운 정보 확보의 효과를 검증한 실험이 아닙니다.', '']
    fmt = lambda x: '—' if x is None else f'{x*100:.2f}'
    for h, q in result['horizons'].items():
        lines += [f"## {'6개월' if h == '126' else '1년'}", '',
            f"동일 {q['evaluation']['priceOnly']['n']}개 표본·{len(q['evaluatedDates'])}개 기준일. 항상 상승 적중 {fmt(q['evaluation']['priceOnly']['alwaysUpAccuracy'])}%.", '',
            '| 방법 | 가격 MAPE % | 수익률 MAE %p | 최종 수익률 방향 적중 % | 상승 포착 % | 하락 포착 % | 하락 경고 적중 % |',
            '|---|---:|---:|---:|---:|---:|---:|']
        for name, m in q['evaluation'].items():
            lines.append('| '+NAMES[name]+' | '+' | '.join(fmt(m[k]) for k in
                ('dateMeanMape', 'dateMeanReturnMae', 'returnDirectionAccuracy', 'upRecall', 'downRecall', 'downPrecision'))+' |')
        lines += ['', '오차는 날짜별 평균을 동일 가중합니다. 방향 지표는 같은 전체 표본을 사용하며 ±2% 중립입니다. 공동 분포 참조의 상승·하락 포착은 클래스 argmax이고 나머지는 최종 수익률 부호이므로 그 두 정의를 같은 방향 성적으로 섞지 않습니다.', '']
        for name, c in q['checks'].items():
            failures = ', '.join(k for k, v in c.items() if not v)
            lines.append(f"- {NAMES[name]}: {'과거 조건 통과' if q['historicalPassed'][name] else '과거 조건 미통과'}; 미통과 `{failures}`.")
        lines += ['', '| 후보 | 가격 패턴 대비 수익률 MAE 개선 %p | 날짜 묶음 참고 구간 %p |', '|---|---:|---:|']
        for name, paired in q['pairedDateImprovementVsPrice'].items():
            d = paired['returnMae']
            lines.append(f"| {NAMES[name]} | {fmt(d['mean'])} | {fmt(d['interval'][0])} ~ {fmt(d['interval'][1])} |")
        lines += ['', '양수이면 후보 오차가 작습니다. 이미 본 적은 날짜들을 재표집한 참고 구간이며 시장 기준일 간 독립성을 보장하지 않습니다.', '']
        for name in ('conditional_return_mae', 'conditional_price_mape'):
            errors = [f['magnitudeWithFutureTrueClass'][name]['returnMae'] for f in q['diagnosticTrueClassRouting']]
            lines.append(f"- 미래 정답 방향을 알고 크기 전문가를 고르는 비실행 진단 {NAMES[name]}: 수익률 MAE {fmt(np.mean(errors))}%p. 실제 후보 성과·선택·승격에 사용하지 않았습니다.")
        fallback = sum(any(f['modelInfo'][n]['fallback'] for n in
                       ('conditional_return_mae', 'conditional_price_mape')) for f in q['folds'])
        lines += [f'- 클래스 표본 부족으로 풀링 대체한 기준일: {fallback}. 모든 기준일을 성적에 포함했습니다.', '',
            f"참고 분류기의 Brier {q['evaluation']['joint_logistic']['brier']:.4f} / 과거 클래스 비율 기준 {q['evaluation']['joint_logistic']['priorBrier']:.4f}. 새로운 숫자 후보의 확률 성적으로 제시하지 않습니다.", '']
    lines += ['## 해석 제한과 근거', '',
        '- 후보·입력·학습 목표·그리드·평가 구간을 실행 전 고정했으며 결과 후 튜닝은 없습니다. 통과 여부와 별개로 자동 승격·병합하지 않습니다.',
        '- MAE와 MAPE는 다른 손실입니다. MAPE만 줄이면 작은 실제 가격에 더 큰 가중치가 생기므로 하락 포착·상승 포착·수익률 오차·잘못된 경고·큰 오차를 모두 봐야 합니다.',
        '- 조건부 모델은 세 대표값으로 분포를 근사합니다. 그중 최적 값이라는 말은 그 근사와 손실 안에서의 의미이며 실제 미래 수익률 분포의 최적 예측이나 정확한 확률을 뜻하지 않습니다.',
        '- 회귀 학습은 해당 기준일 전에 결과가 확정된 모든 표본을 사용하고, 분류기는 기존처럼 학습/교정 미래 구간을 제거합니다. 모델마다 같은 과거 결과를 다른 역할로 사용합니다.',
        '- 현재 기업 구성의 생존 편향, 적은 시장 날짜와 상관, 수정 가격/공시의 한계가 남아 있습니다. 직접 웹 서비스 AI 우위나 현재 APP 매도 여부를 주장하지 않습니다.',
        '- 미래 발행 후 관측과 거래비용을 검증하지 않았습니다. 종료 수익률 방향과 기간 중 하락 포착은 별도 목표입니다.', '',
        '- [MAPE 회귀와 가중 절대오차: de Myttenaere 외](https://arxiv.org/abs/1605.02541)',
        '- [공식 회귀 손실·표본 가중치 문서](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)',
        '- [MAE, RMSE, MAPE의 평가 차이](https://otexts.com/fpp3/accuracy.html)', '',
        '재현: `python scripts/research_conditional_indicator.py` · 검사: `python scripts/test_conditional_indicator.py`', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT/'research/environment.json')
    parser.add_argument('--output', type=Path, default=FOLDER)
    args = parser.parse_args()
    ppath = FOLDER/'PROTOCOL.json'
    protocol = json.loads(ppath.read_text())
    jpath = ROOT/'research/joint-indicator/PROTOCOL.json'
    joint_protocol = json.loads(jpath.read_text())
    raw = args.source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != protocol['sourceHash'] or \
       hashlib.sha256(jpath.read_bytes()).hexdigest() != protocol['jointProtocolHash']:
        raise ValueError('Inputs differ from registered protocol')
    source = json.loads(raw)
    validate_source(source, protocol)
    validate_issuers(source)
    horizons = evaluate(source, protocol, joint_protocol)
    result = dict(version=protocol['version'], registeredAt=protocol['registeredAt'],
        generatedAt=datetime.now(timezone.utc).isoformat(), sourceCommit=protocol['sourceCommit'],
        parentResearchCommit=protocol['parentResearchCommit'], sourceModel=source['model'],
        sourceGeneratedAt=source['generatedAt'], sourceHash=protocol['sourceHash'],
        protocolHash=hashlib.sha256(ppath.read_bytes()).hexdigest(),
        codeHash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        helperHashes={p: hashlib.sha256((ROOT/'scripts'/p).read_bytes()).hexdigest()
                      for p in ('research_joint_indicator.py', 'research_indicator_blends.py')},
        universeHash=hashlib.sha256((ROOT/'research/universe.json').read_bytes()).hexdigest(),
        sklearnVersion=sklearn.__version__, historicalHoldoutRevisited=True,
        uiChanged=False, liveForecastChanged=False, selection='none', horizons=horizons)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    (args.output/'RESULTS.md').write_text(report(result))
    print('Conditional-loss research completed; no live changes or selected candidate.', flush=True)


if __name__ == '__main__':
    main()
