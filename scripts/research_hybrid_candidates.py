"""Offline, fixed-weight research on saved OOS forecasts. Never changes live models."""
import json, math, hashlib
from pathlib import Path
from build_environment_research import score, direction_checks

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('anchor_force', 'price_force', 'sec_agreement')
BASES = ('noChange', 'priceOnly', 'balanced', 'horizonModel', 'secDynamics')

def candidates(row):
    # Fixed choices, no holdout optimization. All inputs are stored OOS predictions.
    p, f = row['priceOnly'], row['horizonModel']
    return {
        'anchor_force': .5 + .5*f,
        'price_force': .5*p + .5*f,
        # The SEC classifier acts only as a veto, never as a substitute price.
        'sec_agreement': f if f < .98 and row['secDynamicsDirection'] == -1 else .5*(1+p),
    }

def run(data):
    out = {}
    for horizon in ('126', '252'):
        section = data['stocks'][horizon]; original = section['outcomes']; comp = section['comparison']
        rows = []
        for row in original:
            r = dict(row); r.update(candidates(r)); rows.append(r)
        start = comp['evaluationStart']
        early = [r for r in rows if r['origin'] < start and r['targetDate'] < start]
        late = [r for r in rows if r['origin'] >= start]
        assert len(late) == comp['evaluation']['noChange']['n']
        assert all(r['targetDate'] < start for r in early)
        def summarize(rs):
            return {n: score(rs,n) for n in BASES + NAMES}
        a, b = summarize(early), summarize(late)
        checks = {}
        for n in NAMES:
            m=b[n]; baselines=[b['noChange'],b['priceOnly']]
            wins=sum(m['byDate'][d] < min(x['byDate'][d] for x in baselines) for d in m['byDate']) / m['dates']
            c=dict(enoughDates=m['dates']>=6,
                   logError=m['dateMeanLogMae'] < .95*min(x['dateMeanLogMae'] for x in baselines),
                   average=m['dateMeanMape'] <= min(x['dateMeanMape'] for x in baselines),
                   tail=m['p90'] <= min(x['p90'] for x in baselines), consistency=wins>=.6,
                   **direction_checks(m,baselines))
            c['selectionEligible']=all(direction_checks(a[n],[a['priceOnly'],a['noChange']]).values())
            checks[n]=dict(checks=c,passed=all(c.values()),dateWinRate=wins)
        out[horizon]=dict(early=a,late=b,checks=checks,selectionDates=comp['selectionDates'],evaluationDates=comp['evaluationDates'],evaluationStart=start,
                          secAvailableLate=sum(r['dynamicCount']>0 for r in late),
                          secVetoCases=sum(r['horizonModel']<.98 and r['secDynamicsDirection']==-1 for r in late),
                          byDate={d:summarize([r for r in late if r['origin']==d]) for d in comp['evaluationDates']})
    return out

if __name__ == '__main__':
    path=ROOT/'research/environment.json'; data=json.loads(path.read_text())
    result=dict(sourceSha256=hashlib.sha256(path.read_bytes()).hexdigest(),sourceGeneratedAt=data['generatedAt'],results=run(data), liveForecastChanged=False)
    dest=ROOT/'research/experiments/hybrid-2026-11-01.json'
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(dest)
