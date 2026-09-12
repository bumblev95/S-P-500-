"""Freeze attributed BTC daily price data; never synthesize intraday history."""
import csv,io,json,hashlib,urllib.request
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
URL='https://raw.githubusercontent.com/coinmetrics/data/master/csv/btc.csv'
def collect():
    raw=urllib.request.urlopen(URL,timeout=60).read()
    rows=[]
    for r in csv.DictReader(io.StringIO(raw.decode())):
        day=r['time'][:10]
        if not '2014-01-01'<=day<='2026-08-31':continue
        try:p=float(r['PriceUSD'])
        except (ValueError,KeyError):continue
        if p>0:rows.append(dict(date=day,price=p))
    assert rows and rows[0]['date']=='2014-01-01'
    assert len({r['date'] for r in rows})==len(rows)
    gaps=[]
    for a,b in zip(rows,rows[1:]):
        if (datetime.fromisoformat(b['date'])-datetime.fromisoformat(a['date'])).days!=1:gaps.append([a['date'],b['date']])
    out=dict(source=URL,provider='Coin Metrics Community',license='CC BY-NC 4.0',licenseUrl='https://creativecommons.org/licenses/by-nc/4.0/',retrievedAt=datetime.now(timezone.utc).isoformat(),rawSha256=hashlib.sha256(raw).hexdigest(),start=rows[0]['date'],end=rows[-1]['date'],gaps=gaps,rows=rows,note='PriceUSD daily observations only. Each dated observation is made available conservatively two UTC days later. No invented OHLC, funding or leveraged returns.')
    dest=ROOT/'simulation/selector-research/btc-daily.json';dest.write_text(json.dumps(out))
    print(json.dumps({k:v for k,v in out.items() if k!='rows'}),len(rows),flush=True)
if __name__=='__main__':collect()
