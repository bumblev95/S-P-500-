"""Versioned current S&P 500 membership; not historical index membership."""
import csv, hashlib, io, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from build_forecasts import atomic_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv'

def parse_members(raw):
    members = {}
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
        symbol = row['Symbol'].strip().upper()
        cik = int(row['CIK'])
        if not re.fullmatch(r'[A-Z0-9]+(?:[.-][A-Z0-9]+)*', symbol) or not 0 < cik < 10**10:
            raise ValueError('Invalid constituent identity')
        if symbol in members: raise ValueError('Duplicate constituent ticker: '+symbol)
        members[symbol] = dict(cik=cik, name=row['Security'].strip(), sector=row['GICS Sector'].strip(),
                               yahooSymbol=symbol.replace('.', '-'))
    if not 450 <= len(members) <= 550 or len({v['cik'] for v in members.values()}) < 450:
        raise ValueError('Unexpected S&P 500 membership size')
    return dict(sorted(members.items()))

def load_universe(root=ROOT):
    data=json.loads((root/'research/universe.json').read_text())
    if not data.get('members'): raise ValueError('Research universe is empty')
    return data

def refresh(root=ROOT):
    request=Request(SOURCE,headers={'User-Agent':'PublicStockDashboard/1.0'})
    with urlopen(request,timeout=30) as response: raw=response.read()
    members=parse_members(raw)
    out=dict(schemaVersion=1,name='S&P 500 current constituents',retrievedAt=datetime.now(timezone.utc).isoformat(),
             source=SOURCE,sourceHash=hashlib.sha256(raw).hexdigest(),members=members,
             tickerCount=len(members),issuerCount=len({v['cik'] for v in members.values()}),
             limitation='Current constituent snapshot. Historical backtests retain survivorship and current-membership selection bias.')
    atomic_json(root/'research/universe.json',out)
    print('Universe:',out['tickerCount'],'tickers;',out['issuerCount'],'issuers',flush=True)
    return out

def targets(root=ROOT, fallback=None):
    if not (root/'research/universe.json').exists():
        if fallback is not None: return dict(fallback)
        raise ValueError('Run research_universe.py before collection')
    return {s:v['cik'] for s,v in load_universe(root)['members'].items()}

if __name__=='__main__': refresh()
