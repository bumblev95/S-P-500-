"""Validate cached stock inputs against the fixed v7 experiment."""
from pathlib import Path
import hashlib,json,math

ROOT=Path(__file__).resolve().parents[1]
BASE_HASH='287f4280b23def1489ad7062fbe35994f56f20ca7bd756bedb9bad85a374b08a'

def audit(root=ROOT):
    p=root/'research/environment.json'
    if hashlib.sha256(p.read_bytes()).hexdigest()!=BASE_HASH:
        raise ValueError('Baseline changed')
    baseline=json.loads(p.read_text())
    required=sorted(set(baseline['stockUniverse'])|set(baseline['contextLabels']))
    history={};checks={};bad=[]
    for s in required:
        name=s.replace('^','INDEX_')+'.json';p=root/'research/history'/name
        sha=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        expected=baseline['historyHashes'].get(name)
        checks[s]=dict(expected=expected,actual=sha,matched=bool(sha and expected==sha))
        if not checks[s]['matched']:bad.append(s)
        elif p.exists():history[s]={r['date']:r['close'] for r in json.loads(p.read_text())['prices']}
    count=0;maxdiff=0.
    if not bad:
        for g in baseline['stocks'].values():
            for r in g['outcomes']:
                prices=history[r['symbol']]
                actual=prices[r['targetDate']]/prices[r['origin']]
                diff=abs(actual-r['y']);maxdiff=max(maxdiff,diff);count+=1
                if diff>1e-12:raise ValueError('Archived target changed: '+r['symbol']+' '+r['origin'])
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (root/'research/source-cache').glob('*.json') if not p.name.startswith('funding')}
    result=dict(baselineHash=BASE_HASH,priceFiles=len(required),matchedPriceFiles=len(required)-len(bad),
        priceChecks=checks,mismatched=bad,matchedTargets=count,maxTargetDifference=maxdiff,
        secSourceFiles=len(sources),secSourceHashes=sources,passed=not bad)
    out=root/'research/experiments/2026-09-13/input-audit.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('priceChecks','secSourceHashes')}),flush=True)
    if bad:raise ValueError('Missing or changed price cache: '+', '.join(bad))
    return result

if __name__=='__main__':audit()
