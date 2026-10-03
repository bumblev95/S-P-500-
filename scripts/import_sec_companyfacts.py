"""Import already-obtained official CompanyFacts JSON or its bulk ZIP, without network requests."""
import argparse, hashlib, json, re, zipfile
from datetime import datetime, timezone
from pathlib import Path
from build_forecasts import atomic_json
from build_research_inputs import ROOT, CIKS as PILOT_CIKS, TAGS, financial_history, sec_coverage
from research_universe import targets
from sec_fallbacks import PREDECESSORS, PARSER_VERSION, POLICY_HASH, parse_cik, diagnostics
CIKS=targets(ROOT,PILOT_CIKS)

def validated(raw, expected=None, configured=None, allow_empty=False):
    configured=configured if configured is not None else CIKS
    payload=json.loads(raw);cik=parse_cik(payload.get('cik'))
    allowed=set(configured.values()) | {p['sourceCIK'] for c,p in PREDECESSORS.items() if c in configured.values()}
    if cik not in allowed:
        raise ValueError('CompanyFacts issuer is not in the configured company universe')
    if expected is not None and cik!=expected:raise ValueError('ZIP filename and issuer CIK disagree')
    rows=financial_history(payload)
    if not rows and not (allow_empty and cik in PREDECESSORS):raise ValueError('No usable standard annual USD financial statements')
    if any(r['availableDate']>datetime.now(timezone.utc).date().isoformat() for r in rows):
        raise ValueError('Future filing dates in imported data')
    return cik,payload,rows

def read_inputs(paths,configured=None):
    configured=configured if configured is not None else CIKS
    allowed=set(configured.values()) | {p['sourceCIK'] for c,p in PREDECESSORS.items() if c in configured.values()}
    found={}
    for path in map(Path,paths):
        if path.suffix.lower()=='.zip':
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    match=re.fullmatch(r'CIK(\d{10})\.json',Path(info.filename).name)
                    if not match or int(match[1]) not in allowed:continue
                    if info.file_size>100_000_000:raise ValueError('Unexpectedly large issuer JSON')
                    raw=archive.read(info);cik,payload,rows=validated(raw,int(match[1]),configured,True)
                    if cik in found:raise ValueError('Duplicate issuer; choose one complete CompanyFacts file per company')
                    found[cik]=(payload,rows,hashlib.sha256(raw).hexdigest())
        else:
            raw=path.read_bytes();cik,payload,rows=validated(raw,configured=configured,allow_empty=True)
            if cik in found:raise ValueError('Duplicate issuer; choose one complete CompanyFacts file per company')
            found[cik]=(payload,rows,hashlib.sha256(raw).hexdigest())
    if not found:raise ValueError('No configured CompanyFacts JSON found; quarterly SUB/NUM ZIPs use a different format')
    return found

def ingest(paths,root=ROOT):
    configured=targets(root,CIKS)
    found=read_inputs(paths,configured);target=root/'research/inputs.json'
    out=json.loads(target.read_text()) if target.exists() else dict(schemaVersion=1,stocks={},funding={},snapshots={},errors=[])
    stocks=out.setdefault('stocks',{});stamp=datetime.now(timezone.utc).isoformat()
    symbols={}
    for s,c in configured.items():symbols.setdefault(c,s)
    prepared={};details={}
    for cik,symbol in symbols.items():
        policy=PREDECESSORS.get(cik)
        predecessor=found.get(policy['sourceCIK']) if policy else None
        current=found.get(cik)
        if current is None and predecessor is not None:
            p=root/'research/source-cache'/(symbol+'.json')
            if not p.exists():raise ValueError('Predecessor import also requires the current CompanyFacts file')
            raw=p.read_bytes();_,payload,rows=validated(raw,cik,configured,True)
            current=(payload,rows,hashlib.sha256(raw).hexdigest())
        if current is None:continue
        payload,_,digest=current
        rows=financial_history(payload,predecessor[0] if predecessor else None)
        if not rows:raise ValueError('No usable standard annual USD financial statements for '+symbol)
        if any(r['availableDate']>datetime.now(timezone.utc).date().isoformat() for r in rows):raise ValueError('Future filing dates in imported data')
        prepared[cik]=(payload,rows,digest)
        details[str(cik)]=diagnostics(payload,rows,TAGS['revenue'],predecessor[0] if predecessor else None)
    # Validate all input files before replacing any existing source history.
    for cik,(_,rows,_) in prepared.items():
        prior=stocks.get(symbols[cik],{}).get('rows',[])
        if prior and (rows[0]['availableDate']>prior[0]['availableDate'] or rows[-1]['availableDate']<prior[-1]['availableDate']):
            raise ValueError('Imported history would shorten existing coverage for '+symbols[cik])
    for cik,(payload,rows,digest) in prepared.items():
        symbol=symbols[cik]
        atomic_json(root/'research/source-cache'/f'{symbol}.json',payload)
        stocks[symbol]=dict(cik=cik,source='SEC companyfacts / imported annual US-GAAP',rows=rows,
                            retrievedAt=None,importedAt=stamp,sourceHash=digest,parserVersion=PARSER_VERSION,
                            fallbackPolicyHash=POLICY_HASH,
                            sourcePayloadHashes=details[str(cik)]['sourcePayloadHashes'])
    for source_cik,(payload,_,_) in found.items():
        if source_cik not in symbols:atomic_json(root/'research/source-cache'/f'CIK{source_cik:010d}.json',payload)
    for symbol,cik in configured.items():
        if cik in prepared: stocks[symbol]=dict(stocks[symbols[cik]])
    out['generatedAt']=stamp
    prior=out.get('secCoverage',{})
    diagnostic=dict(prior.get('diagnostics',{}));diagnostic.update({c:{**d,'processedAt':stamp,'collectionMode':'imported'} for c,d in details.items()})
    status=dict(prior.get('status',{}));status.update({str(c):'imported' for c in prepared})
    out['secCoverage']=sec_coverage(configured,stocks,status,diagnostic,requests=0)
    # Access-denial backoff remains in force; import success does not prove API access.
    atomic_json(target,out)
    print('Imported SEC histories:',', '.join(symbols[c] for c in prepared),flush=True)
    return out

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files',nargs='+',help='Official CompanyFacts JSON files or companyfacts.zip')
    ingest(parser.parse_args().files)
