"""Publish a compact dashboard view of the frozen SEC validation experiments.

This is a report builder, not another fit or a production model selector.
Run against the archived inputs in the same revision as the experiment results.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path('research/experiments/2026-09-13')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root=ROOT):
    folder = root / FOLDER
    names = ('e0-calibration.json', 'e1-ranking.json', 'e2-input-audit.json',
             'e2-quarterly.json', 'e3-verification.json', 'input-audit.json')
    e0, e1, audit, e2, e3, inputs = [json.loads((folder / n).read_text()) for n in names]
    baseline = root / 'research/environment.json'
    if sha(baseline) != e0['inputHash'] or inputs['baselineHash'] != e0['inputHash']:
        raise ValueError('The report requires its frozen environment input')
    if not inputs['passed'] or not e3['passed']:
        raise ValueError('Input and replay verification must pass before publishing completion')
    if e2['inputAuditHash'] != sha(folder / 'e2-input-audit.json'):
        raise ValueError('Quarterly result and source audit do not match')
    for data, script, protocol in (
        (e1, 'run_stock_ranking_experiment.py', 'PROTOCOL.md'),
        (e2, 'run_stock_quarterly_experiment.py', 'E2-PROTOCOL.md'),
    ):
        if data['codeHash'] != sha(root / 'scripts' / script):
            raise ValueError('Experiment implementation changed since the recorded run')
        if data['protocolHash'] != sha(folder / protocol):
            raise ValueError('Experiment protocol changed since the recorded run')
    if e3['prospective']['fileHash'] != sha(folder / 'e1-issued.json'):
        raise ValueError('First issued research scores changed')
    if e1['productionPromoted'] or e2['productionPromoted'] or e3['productionPromoted']:
        raise ValueError('This frozen research report does not authorize a production change')
    coverage = json.loads(baseline.read_text())['universeCoverage']
    selected = e1['selected']
    rankings = []
    labels = {
        'ridgeAbsolute': 'Ridge · 종목 수익률',
        'ridgeRelative': 'Ridge · 시장 대비 수익률',
        'treeAbsolute': '트리 · 종목 수익률',
        'treeRelative': '트리 · 시장 대비 수익률',
        'momentum': '180일 모멘텀 기준',
    }
    for name, label in labels.items():
        early, late = (e1['scores'][s][name] for s in ('selection', 'evaluation'))
        rankings.append(dict(key=name, label=label, selected=name == selected,
                             earlierIc=early['dateMeanIc'], laterIc=late['dateMeanIc']))
    fitted = e2['additionalConfigurationsFitted']
    if fitted:
        if not all(e2['sourceChecks'].values()) or min(e2['completeBaseCoverage'].values()) < .5:
            raise ValueError('Quarterly fitting was not eligible under the fixed protocol')
        rankings.append(dict(key='quarterlyRidge', label='Ridge · 분기 실적 추가', selected=False,
                             earlierIc=e2['scores']['selection']['dateMeanIc'],
                             laterIc=e2['scores']['evaluation']['dateMeanIc']))
    calibration = []
    for horizon, group in e0['horizons'].items():
        m = group['evaluation']
        calibration.append(dict(months=int(horizon) // 21, selected=group['selected'],
                                eligible=group['laterEligible'], dates=m['raw']['dates'],
                                rawAuc=m['raw']['dateMeanAuc'], legacyAuc=m['legacy']['dateMeanAuc'],
                                monotoneAuc=m['sigmoid8']['dateMeanAuc'],
                                monotoneBrier=m['sigmoid8']['dateMeanBrier'],
                                priorBrier=m['prior']['dateMeanBrier']))
    result = dict(
        schemaVersion=1, studyDate='2026-09-13', completedAt=e3['completedAt'],
        status='completed', productionPromoted=False,
        configurations=e0['newConfigurations'] + len(e1['configurations']) + fitted,
        coverage=dict(targetIssuers=audit['targetIssuers'], targetTickers=coverage['targetTickers'],
                      secSourceIssuers=audit['sourceIssuers'], annualUsableIssuers=coverage['sec']['usableIssuers'],
                      priceIssuers=coverage['priceIssuers'], completeQuarterlyCoverage=e2.get('completeBaseCoverage'),
                      releaseChecks=audit['releaseControlCounts']),
        calibration=calibration,
        ranking=dict(selected=selected, laterEligible=e1['laterEligible'],
                     dates=e1['scores']['evaluation'][selected]['dates'],
                     rows=e1['scores']['evaluation'][selected]['n'],
                     uncertainty=e1['uncertainty'][selected]['descriptiveDateBootstrap95'], models=rankings),
        quarterly=dict(status=e2['status'], fitted=fitted, earlierImproves=e2.get('earlierImproves'),
                       laterEligible=e2.get('laterEligible', False), valuationFitted=e2['valuationFitted']),
        verification=dict(passed=e3['passed'], rows=e3['fullForecastRows'], replayRows=e3['replayRows'],
                          replayOrigin=e3['replayOrigin'], maxDifference=max(e3['maxPredictionDifference'].values()),
                          priceFiles=e3['inputChecks']['priceFiles'], targets=e3['inputChecks']['matchedTargets']),
        prospective=e3['prospective'],
        sourceHashes={n: sha(folder / n) for n in names},
        workflowUrl='https://github.com/bumblev95/S-P-500-/actions/runs/34776960624',
    )
    (folder / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'configurations', 'productionPromoted', 'coverage')}, ensure_ascii=False))
    return result


if __name__ == '__main__':
    build()
