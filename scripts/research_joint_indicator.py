"""Causal research on a joint direction/return distribution; never writes live data.

Uses the existing challenger's historical OOS forecasts as stacking features.
Every fit, calibration and distribution-shape label must have matured before
the evaluated forecast. The three candidates and heldout split are fixed in
research/joint-indicator/PROTOCOL.json. Revisited history is not a fresh test.
"""
from __future__ import annotations

import os
os.environ.setdefault('OMP_NUM_THREADS', '2')
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
LABELS = np.array([-1, 0, 1])
BASELINES = ('noChange', 'priceOnly', 'balanced', 'independentReturn', 'secDynamics')
NAMES = {'noChange': '가격 불변', 'priceOnly': '가격 패턴', 'balanced': '기존 균형 연구',
         'independentReturn': '기존 방향 분류', 'secDynamics': '기존 SEC 변화 분류',
         'joint_logistic': '공동 분포 · 로지스틱',
         'joint_balanced_logistic': '공동 분포 · 균형 로지스틱',
         'joint_tree': '공동 분포 · 트리'}


def label(ratio):
    values = np.asarray(ratio)
    return np.where(values > 1.02, 1, np.where(values < .98, -1, 0))


def date_weights(rows):
    counts = Counter(r['origin'] for r in rows)
    return np.array([len(rows) / (len(counts) * counts[r['origin']]) for r in rows])


def matrix(rows):
    """Only contemporaneous OOS forecasts and explicitly known context flags."""
    result = []
    for row in rows:
        values = [np.log(row[k]) for k in
                  ('priceOnly', 'environment', 'balanced', 'independentReturn', 'secDynamics')]
        for key in ('independentReturnScores', 'secDynamicsScores'):
            raw = np.clip(row[key]['raw'], 1e-6, 1)
            values += [float(np.log(raw[0] / raw[2])), float(np.log(raw[1] / raw[2]))]
        values += [float(row['regime'].startswith('하락')),
                   float('고변동' in row['regime']), row['inputCount'] / 20]
        result.append(values)
    return np.asarray(result, dtype=float)


def validate_source(source, protocol):
    through = source['generatedAt'][:10]
    for h in protocol['horizons']:
        data = source['stocks'][str(h)]
        for fold in data['folds']:
            if fold['trainTargetThrough'] >= fold['origin']:
                raise ValueError('Base-model training reaches its forecast origin')
        for row in data['outcomes']:
            if not row['origin'] < row['targetDate'] <= through:
                raise ValueError('Outcome has not matured by the input snapshot')
            if any(row.get(k) and row[k] >= row['origin'] for k in ('inputThrough', 'contextThrough')):
                raise ValueError('Input was not available before forecast origin')
            if any(not np.isfinite(row[k]) or row[k] <= 0 for k in
                   ('y', 'priceOnly', 'environment', 'balanced', 'independentReturn', 'secDynamics')):
                raise ValueError('Non-positive or non-finite price-ratio input')
            for key in ('independentReturnScores', 'secDynamicsScores'):
                probability = np.asarray(row[key]['raw'])
                if probability.shape != (3,) or not np.isfinite(probability).all() or \
                   np.any(probability < 0) or not np.isclose(probability.sum(), 1):
                    raise ValueError('Invalid base-classifier scores')


def split_matured(rows, origin, protocol):
    matured = [r for r in rows if r['origin'] < origin and r['targetDate'] < origin]
    dates = sorted({r['origin'] for r in matured})
    n = protocol['calibrationDates']
    if len(dates) < protocol['minimumFitDates'] + n:
        return None
    cal_dates = dates[-n:]
    # Purge outcomes that overlap the start of calibration, not just its rows.
    fit = [r for r in matured if r['targetDate'] < cal_dates[0]]
    cal = [r for r in matured if r['origin'] in cal_dates]
    if len({r['origin'] for r in fit}) < protocol['minimumFitDates']:
        return None
    if any(sum(label(r['y']) == c for r in fit) < 20 for c in LABELS):
        return None
    if any(sum(label(r['y']) == c for r in cal) < 10 for c in LABELS):
        return None
    return fit, cal, matured


def ordered_probability(model, x):
    probability = model.predict_proba(x)
    order = [list(model.classes_).index(int(c)) for c in LABELS]
    return probability[:, order]


class Mixture:
    """Disjoint down/flat/up empirical supports define one valid distribution."""
    def __init__(self, rows):
        self.support = []
        for c in LABELS:
            own = [r for r in rows if label(r['y']) == c]
            values = np.array([r['y'] for r in own])
            weights = date_weights(own)
            order = np.argsort(values, kind='stable')
            cumulative = np.cumsum(weights[order]) / weights.sum()
            self.support.append((values[order], cumulative))

    def quantiles(self, probability, quantiles=(.1, .5, .9)):
        result = np.empty((len(probability), len(quantiles)))
        cumulative = probability.cumsum(axis=1)
        for i, p in enumerate(probability):
            for j, q in enumerate(quantiles):
                k = min(int(np.searchsorted(cumulative[i], q, side='left')), 2)
                previous = cumulative[i, k-1] if k else 0.
                local = np.clip((q - previous) / max(p[k], 1e-15), 0, 1)
                values, masses = self.support[k]
                result[i, j] = values[min(np.searchsorted(masses, local, side='left'), len(values)-1)]
        return result


def predict_candidate(name, fit, calibration, matured, test):
    x = matrix(fit)
    y = label([r['y'] for r in fit])
    weights = date_weights(fit)
    if name != 'joint_logistic':
        prevalence = np.array([weights[y == c].sum() / weights.sum() for c in LABELS])
        weights = weights * np.array([prevalence[int(c)+1] ** -.5 for c in y])
        weights *= len(weights) / weights.sum()
    scaler = None
    if name == 'joint_tree':
        model = HistGradientBoostingClassifier(max_iter=45, max_leaf_nodes=7,
            min_samples_leaf=60, l2_regularization=20, learning_rate=.04,
            early_stopping=False, random_state=23)
    else:
        scaler = StandardScaler().fit(x, sample_weight=date_weights(fit))
        x = scaler.transform(x)
        model = LogisticRegression(C=.1, max_iter=500, random_state=23)
    model.fit(x, y, sample_weight=weights)
    transform = lambda rows: scaler.transform(matrix(rows)) if scaler else matrix(rows)
    cal_raw = ordered_probability(model, transform(calibration))
    calibrator = LogisticRegression(C=1, max_iter=500, random_state=23)
    calibrator.fit(np.log(np.clip(cal_raw, 1e-6, 1)),
                   label([r['y'] for r in calibration]), sample_weight=date_weights(calibration))
    raw = ordered_probability(model, transform(test))
    probability = ordered_probability(calibrator, np.log(np.clip(raw, 1e-6, 1)))
    low, point, high = Mixture(matured).quantiles(probability).T
    prior = np.array([np.sum(date_weights(matured)[label([r['y'] for r in matured]) == c])
                      for c in LABELS])
    prior /= prior.sum()
    return [dict(value=float(value), direction=int(LABELS[np.argmax(p)]),
                 probability=p.tolist(), prior=prior.tolist(), low=float(lo), high=float(hi))
            for p, value, lo, hi in zip(probability, point, low, high)]


def score(rows, name):
    actual = np.array([r['y'] for r in rows])
    forecast = np.array([r['methods'][name]['value'] for r in rows])
    directions = np.array([r['methods'][name]['direction'] for r in rows])
    truth = label(actual)
    error = abs(forecast / actual - 1)
    origins = sorted({r['origin'] for r in rows})
    by_date = {}
    for day in origins:
        mask = np.array([r['origin'] == day for r in rows])
        by_date[day] = dict(mape=float(error[mask].mean()),
            directionAccuracy=float((truth[mask] == directions[mask]).mean()),
            alwaysUpAccuracy=float((truth[mask] == 1).mean()))
    recalls = {str(c): float(np.mean(directions[truth == c] == c))
               if np.any(truth == c) else None for c in LABELS}
    predicted_down = directions == -1
    out = dict(n=len(rows), dates=len(origins), mape=float(error.mean()),
        dateMeanMape=float(np.mean([v['mape'] for v in by_date.values()])),
        p90Mape=float(np.quantile(error, .9)),
        logMae=float(np.mean(abs(np.log(forecast / actual)))),
        directionAccuracy=float(np.mean(directions == truth)),
        returnDirectionAccuracy=float(np.mean(label(forecast) == truth)),
        balancedDirectionAccuracy=float(np.mean([v for v in recalls.values() if v is not None])),
        upRecall=recalls['1'], downRecall=recalls['-1'], flatRecall=recalls['0'],
        downPrecision=float(np.mean(truth[predicted_down] == -1)) if predicted_down.any() else None,
        downPrevalence=float(np.mean(truth == -1)),
        alwaysUpAccuracy=float(np.mean(truth == 1)),
        directionCounts={str(c): int(np.sum(directions == c)) for c in LABELS}, byDate=by_date)
    if 'probability' in rows[0]['methods'][name]:
        probability = np.array([r['methods'][name]['probability'] for r in rows])
        prior = np.array([r['methods'][name]['prior'] for r in rows])
        onehot = (truth[:, None] == LABELS).astype(float)
        weights = date_weights(rows)
        low = np.array([r['methods'][name]['low'] for r in rows])
        high = np.array([r['methods'][name]['high'] for r in rows])
        out.update(brier=float(np.average(((probability-onehot)**2).sum(axis=1), weights=weights)),
            priorBrier=float(np.average(((prior-onehot)**2).sum(axis=1), weights=weights)),
            rangeCoverage=float(np.average((low <= actual) & (actual <= high), weights=weights)),
            directionReturnAgreement=float(np.mean(label(forecast) == directions)))
    return out


def direction_ci(metrics):
    """Resample dates, never pretend contemporaneous issuers are independent."""
    diff = np.array([q['directionAccuracy']-q['alwaysUpAccuracy'] for q in metrics['byDate'].values()])
    sample = np.random.default_rng(23).choice(diff, size=(2000, len(diff)), replace=True).mean(axis=1)
    return [float(v) for v in np.quantile(sample, [.025, .975])]


def gates(metrics, baseline, no_change, protocol):
    g = protocol['gate']
    wins = np.mean([m['mape'] < min(baseline['byDate'][d]['mape'], no_change['byDate'][d]['mape'])
                    for d, m in metrics['byDate'].items()])
    return dict(enoughDates=metrics['dates'] >= g['minimumEvaluationDates'],
        priceError=metrics['dateMeanMape'] <= (1-g['priceErrorImprovement']) *
                   min(baseline['dateMeanMape'], no_change['dateMeanMape']),
        tail=metrics['p90Mape'] <= min(baseline['p90Mape'], no_change['p90Mape']),
        dateConsistency=bool(wins >= g['minimumDateWinRate']),
        direction=metrics['directionAccuracy'] > max(metrics['alwaysUpAccuracy'], baseline['directionAccuracy']),
        returnDirection=metrics['returnDirectionAccuracy'] > max(metrics['alwaysUpAccuracy'], baseline['returnDirectionAccuracy']),
        balancedDirection=metrics['balancedDirectionAccuracy'] > max(1/3, baseline['balancedDirectionAccuracy']),
        upRecall=metrics['upRecall'] is not None and metrics['upRecall'] >= g['minimumUpRecall'],
        downRecall=metrics['downRecall'] is not None and metrics['downRecall'] >= g['minimumDownRecall'],
        downPrecision=metrics['downPrecision'] is not None and
                      metrics['downPrecision'] >= metrics['downPrevalence'] + g['minimumDownPrecisionLift'],
        probability=metrics['brier'] < metrics['priorBrier'],
        directionEvidence=direction_ci(metrics)[0] > 0,
        prospective=False)


def evaluate(source, protocol):
    result = {}
    for h in protocol['horizons']:
        rows = source['stocks'][str(h)]['outcomes']
        origins = sorted({r['origin'] for r in rows})
        start = origins[len(origins)//2]
        evaluated, folds = [], []
        for day in origins:
            if day < start:
                continue
            split = split_matured(rows, day, protocol)
            if split is None:
                folds.append(dict(origin=day, status='insufficient_matured_fit_or_calibration'))
                continue
            fit, cal, matured = split
            test = [r for r in rows if r['origin'] == day]
            print(h, day, 'fit', len(fit), 'calibration', len(cal), 'test', len(test), flush=True)
            predictions = {name: predict_candidate(name, fit, cal, matured, test)
                           for name in protocol['candidates']}
            for i, row in enumerate(test):
                methods = {name: dict(value=float(row[name]),
                    direction=int(row.get(name+'Direction', label(row[name])))) for name in BASELINES}
                methods.update({name: values[i] for name, values in predictions.items()})
                evaluated.append(dict(symbol=row['symbol'], origin=day, targetDate=row['targetDate'],
                    y=row['y'], regime=row['regime'], methods=methods))
            folds.append(dict(origin=day, status='evaluated', fitDates=len({r['origin'] for r in fit}),
                fitRows=len(fit), fitTargetThrough=max(r['targetDate'] for r in fit),
                calibrationStart=min(r['origin'] for r in cal), calibrationRows=len(cal),
                calibrationTargetThrough=max(r['targetDate'] for r in cal),
                shapeTargetThrough=max(r['targetDate'] for r in matured), testRows=len(test)))
        if not evaluated:
            result[str(h)] = dict(status='insufficient', folds=folds)
            continue
        metrics = {name: score(evaluated, name) for name in (*BASELINES, *protocol['candidates'])}
        checks = {name: gates(metrics[name], metrics['priceOnly'], metrics['noChange'], protocol)
                  for name in protocol['candidates']}
        regimes = {regime: {name: score([r for r in evaluated if r['regime'] == regime], name)
                   for name in metrics} for regime in sorted({r['regime'] for r in evaluated})}
        result[str(h)] = dict(status='research', evaluationStart=start,
            evaluatedDates=sorted({r['origin'] for r in evaluated}), evaluation=metrics,
            regimes=regimes, checks=checks,
            historicalPassed={name: all(v for k, v in c.items() if k != 'prospective') for name, c in checks.items()},
            passed={name: all(c.values()) for name, c in checks.items()},
            directionImprovementCI={name: direction_ci(metrics[name]) for name in protocol['candidates']},
            selected=None, folds=folds,
            pairedRowsHash=hashlib.sha256(json.dumps(evaluated, sort_keys=True).encode()).hexdigest())
    return result


def report(result):
    lines = ['# 상승·하락 방향과 수익률 공동 연구', '',
        f"생성: {result['generatedAt']} · 기준 커밋: `{result['sourceCommit']}`", '',
        '웹 화면·서비스 모델·매수/매도 순위를 변경하지 않은 연구입니다. 기존 연구의 과거 외부표본 예측을 입력으로 재사용한 탐색이며, 새로운 실전 검증 결과가 아닙니다.', '',
        '동일한 분포에서 상승·횡보·하락 점수와 수익률 중앙값을 계산했습니다. 방향은 가장 큰 클래스 점수이며, 중앙값의 부호와 다를 수 있어 두 방향 성적을 각각 평가합니다. 종목의 실제 당일 수익률을 입력하지 않습니다.', '']
    for h, q in result['horizons'].items():
        lines += [f"## {'6개월' if h == '126' else '1년'}", '']
        if q['status'] == 'insufficient':
            lines += ['학습·교정 결과가 확정된 날짜가 부족합니다.', '']
            continue
        lines += [f"동일 표본 {q['evaluation']['priceOnly']['n']}개 · {len(q['evaluatedDates'])}개 날짜. 항상 상승 기준 {q['evaluation']['priceOnly']['alwaysUpAccuracy']*100:.2f}%.", '',
            '| 방법 | 날짜별 가격 오차 | 방향 적중 | 수익률 부호 적중 | 상승 포착 | 하락 포착 | 하락 경고 적중 |',
            '|---|---:|---:|---:|---:|---:|---:|']
        percent = lambda x: '—' if x is None else f'{x*100:.2f}%'
        for name, m in q['evaluation'].items():
            lines.append('| '+NAMES[name]+' | '+' | '.join(percent(m[k]) for k in
                ('dateMeanMape', 'directionAccuracy', 'returnDirectionAccuracy', 'upRecall', 'downRecall', 'downPrecision'))+' |')
        lines += ['', '가격 오차는 미래 실제 가격 대비 MAPE입니다. 방향은 ±2%를 중립으로 분류합니다. 하락 경고 적중률과 하락 포착률은 서로 다른 지표입니다.', '']
        for name, c in q['checks'].items():
            failed = ', '.join(k for k, v in c.items() if not v)
            lines.append(f"- {NAMES[name]}: {'과거 조건 통과' if q['historicalPassed'][name] else '과거 조건 미통과'}; 미통과 `{failed}`.")
        lines += ['', '후반 성적을 보고 후보나 문턱을 바꾸지 않았습니다. 후보 선택·자동 승격은 없습니다.', '']
    lines += ['## 제한과 다음 연구', '',
        '- 현재 구성 기업을 과거에 적용한 생존 편향이 남아 있습니다.',
        '- 같은 날짜의 종목들은 독립된 시장 상황이 아닙니다. 날짜를 묶어 방향 개선 차이의 참고 구간을 계산했으며, 날짜 간 독립도 보장되지 않습니다.',
        '- 이 비교의 가격 패턴 기준은 기존 연구 모델입니다. 다른 표본을 사용하는 웹 서비스 AI와의 직접 우위 비교가 아닙니다.',
        '- 분포 범위는 연구 추정치입니다. 미래 포함 확률이나 수익을 보장하지 않습니다.',
        '- 상승·하락장 및 고변동장 성적을 분리하고, 새로운 발행 후 관측을 확보해야 합니다.',
        '- 다음 연구에서는 종목이 시장·업종에 비해 약해지는 정도를 분리하고, 날짜별 성적과 잘못된 매도 경고 비용을 함께 비교합니다.', '',
        '재현: `python scripts/research_joint_indicator.py` · 검증: `python scripts/test_joint_indicator.py`', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT/'research/environment.json')
    parser.add_argument('--output', type=Path, default=ROOT/'research/joint-indicator')
    args = parser.parse_args()
    protocol_path = ROOT/'research/joint-indicator/PROTOCOL.json'
    protocol = json.loads(protocol_path.read_text())
    raw = args.source.read_bytes()
    source = json.loads(raw)
    validate_source(source, protocol)
    result = dict(version=protocol['version'], generatedAt=datetime.now(timezone.utc).isoformat(),
        sourceCommit=protocol['sourceCommit'], sourceModel=source['model'],
        sourceGeneratedAt=source['generatedAt'], sourceHash=hashlib.sha256(raw).hexdigest(),
        protocolHash=hashlib.sha256(protocol_path.read_bytes()).hexdigest(), sklearnVersion=sklearn.__version__,
        horizonModelsIndependent=True, liveForecastChanged=False, uiChanged=False,
        selection='none', historicalHoldoutRevisited=True, horizons=evaluate(source, protocol))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    (args.output/'RESULTS.md').write_text(report(result))
    print('Research completed; no live forecast or UI changes.', flush=True)


if __name__ == '__main__':
    main()
