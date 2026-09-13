"""Recover missing SEC raw payloads separately; never change frozen E0/E1 inputs."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,time
from urllib.error import HTTPError
from build_research_inputs import request,sec_identity
from build_forecasts import atomic_json

ROOT=Path(__file__).resolve().parents[1]

def collect(root=ROOT):
    exp=root/'research/experiments/2026-09-13';folder=exp/'sec-supplement';folder.mkdir(exist_ok=True)
    path=exp/'e2-supplement-manifest.json'
    manifest=json.loads(path.read_text()) if path.exists() else dict(purpose='E2 missing raw SEC payloads',sources={},errors=[])
    members=json.loads((root/'research/universe.json').read_text())['members']
    existing=set()
    for p in (root/'research/source-cache').glob('*.json'):
        payload=json.loads(p.read_text())
        if isinstance(payload,dict) and 'cik' in payload and 'facts' in payload:existing.add(int(payload['cik']))
    wanted={}
    for symbol,r in sorted(members.items()):
        if r['cik'] not in existing:wanted.setdefault(r['cik'],symbol)
    # Use the existing repository contact configuration; never print its value.
    if wanted:sec_identity()
    for cik,symbol in wanted.items():
        name=symbol+'.json';p=folder/name;old=manifest['sources'].get(name)
        if old and p.exists():
            if hashlib.sha256(p.read_bytes()).hexdigest()!=old['sha256']:raise ValueError('Supplement hash mismatch')
            continue
        url=f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'
        try:
            payload=request(url)
            if int(payload.get('cik',-1))!=cik:raise ValueError('Supplement issuer mismatch')
            atomic_json(p,payload)
            manifest['sources'][name]=dict(cik=cik,symbol=symbol,url=url,
                retrievedAt=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            atomic_json(path,manifest)
            print('Recovered missing SEC payload:',symbol,flush=True)
        except Exception as exc:
            manifest['errors'].append(dict(symbol=symbol,error=str(exc),at=datetime.now(timezone.utc).isoformat()))
            atomic_json(path,manifest)
            if isinstance(exc,HTTPError) and exc.code in (401,403,429):break
            raise
        time.sleep(.25)
    atomic_json(path,manifest)
    print('Supplement payloads:',len(manifest['sources']),'errors:',len(manifest['errors']),flush=True)

if __name__=='__main__':collect()
