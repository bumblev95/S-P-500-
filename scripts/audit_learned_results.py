"""Fail the daily publication if chronological validation invariants break."""
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def audit(root=ROOT):
    latest=json.loads((root/'ml/latest.json').read_text())
    if latest.get('status')!='trained':raise ValueError('No trained model to audit')
    for h in (126,252):
        source=json.loads((root/f'ml/validation/{h}.json').read_text())
        assert source['model']==latest['model'], 'Model version mismatch'
        assert source['generatedAt']==latest['generatedAt'], 'Validation generation mismatch'
        for f in source['folds']:
            assert f['trainTargetThrough']<f['trainCutoff'], 'Training target leakage'
            assert f['calibrationTargetThrough']<f['origin'], 'Calibration target leakage'
        rows=source['outcomes'];origins=sorted({r['origin'] for r in rows})
        for r in rows:
            assert r['origin']<r['targetDate']<=latest['asOf'], 'Unrealized or invalid target'
            assert all(math.isfinite(r[k]) for k in ('y','pred','low','high','trend')), 'Non-finite outcome'
        for a,b in zip(origins,origins[1:]):
            assert max(r['targetDate'] for r in rows if r['origin']==a)<=b, 'Overlapping test outcomes'
        m=latest['validation'][str(h)]
        assert m['n']==len(rows) and m['dates']==len(origins), 'Inconsistent sample counts'
        assert m['directionAccuracy']<=1 and m['alwaysUpAccuracy']<=1, 'Invalid direction baseline'
        if m['actualDownCount']:
            assert m['downRecall'] is not None, 'Missing decline recall'
        print(f'{h}: {len(rows)} observations / {len(origins)} origins; chronology and direction baselines passed')
    return True

if __name__=='__main__':audit()
