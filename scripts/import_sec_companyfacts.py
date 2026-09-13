"""Import already-obtained official CompanyFacts JSON or its bulk ZIP, without network requests."""
import argparse, hashlib, json, re, zipfile
from datetime import datetime, timezone
from pathlib import Path
from build_forecasts import atomic_json
from build_research_inputs import ROOT, CIKS as PILOT_CIKS, financial_history
from research_universe import targets
CIKS=targets(ROOT,PILOT_CIKS)

def validated(raw, expected=None):
    payload=json.loads(raw);cik=payload.get('cik')
    if isinstance(cik,bool) or not isinstance(cik,int) or cik not in CIKS.values():
        raise ValueError('CompanyFacts issuer is not in the configured company universe')
    if expected is not None and cik!=expected:raise ValueError('ZIP filename and issuer CIK disagree')
    rows=financial_history(payload)
    if not rows:raise ValueError('No usable standard annual USD financial statements')
    if any(r['availableDate']>datetime.now(timezone.utc).date().isoformat() for r in rows):
        raise ValueError('Future filing dates in imported data')
    return cik,payload,rows

def read_inputs(paths):
    found={}
    for path in map(Path,paths):
        if path.suffix.lower()=='.zip':
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    match=re.fullmatch(r'CIK(\d{10})\.json',Path(info.filename).name)
                    if not match or int(match[1]) not in CIKS.values():continue
                    if info.file_size>100_000_000:raise ValueError('Unexpectedly large issuer JSON')
                    raw=archive.read(info);cik,payload,rows=validated(raw,int(match[1]))
                    if cik in found:raise ValueError('Duplicate issuer; choose one complete CompanyFacts file per company')
                    found[cik]=(payload,rows,hashlib.sha256(raw).hexdigest())
        else:
            raw=path.read_bytes();cik,payload,rows=validated(raw)
            if cik in found:raise ValueError('Duplicate issuer; choose one complete CompanyFacts file per company')
            found[cik]=(payload,rows,hashlib.sha256(raw).hexdigest())
    if not found:raise ValueError('No configured CompanyFacts JSON found; quarterly SUB/NUM ZIPs use a different format')
    return found

def ingest(paths,root=ROOT):
    found=read_inputs(paths);target=root/'research/inputs.json'
    out=json.loads(target.read_text()) if target.exists() else dict(schemaVersion=1,stocks={},funding={},snapshots={},errors=[])
    stocks=out.setdefault('stocks',{});stamp=datetime.now(timezone.utc).isoformat()
    symbols={}
    for s,c in CIKS.items():symbols.setdefault(c,s)
    # Validate all input files before replacing any existing source history.
    for cik,(_,rows,_) in found.items():
        prior=stocks.get(symbols[cik],{}).get('rows',[])
        if prior and (rows[0]['availableDate']>prior[0]['availableDate'] or rows[-1]['availableDate']<prior[-1]['availableDate']):
            raise ValueError('Imported history would shorten existing coverage for '+symbols[cik])
    for cik,(payload,rows,digest) in found.items():
        symbol=symbols[cik]
        atomic_json(root/'research/source-cache'/f'{symbol}.json',payload)
        stocks[symbol]=dict(cik=cik,source='SEC companyfacts / imported annual US-GAAP',rows=rows,
                            retrievedAt=None,importedAt=stamp,sourceHash=digest)
    for symbol,cik in CIKS.items():
        if cik in found: stocks[symbol]=dict(stocks[symbols[cik]])
    out['generatedAt']=stamp
    # Access-denial backoff remains in force; import success does not prove API access.
    atomic_json(target,out)
    print('Imported SEC histories:',', '.join(symbols[c] for c in found),flush=True)
    return out

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files',nargs='+',help='Official CompanyFacts JSON files or companyfacts.zip')
    ingest(parser.parse_args().files)
