"""Freeze past-only raw-price features for the registered research protocol."""
import os
os.environ.setdefault('OMP_NUM_THREADS', '2')
import argparse, gzip, hashlib, json, math, time
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'research/joint-indicator/relative-v1'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def fetch(symbol):
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/'+symbol.replace('.', '-')+'?range=20y&interval=1d'
    for attempt in range(2):
        try:
            with urlopen(Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=25) as response:
                raw = response.read()
            q = json.loads(raw)['chart']['result'][0]
            if q['meta']['symbol'].upper() != symbol.replace('.', '-').upper():
                raise ValueError('Asset identity mismatch')
            prices = q['indicators'].get('adjclose', [{}])[0].get('adjclose', q['indicators']['quote'][0]['close'])
            # Never use an in-progress current session; features will be sliced again per origin.
            today = datetime.now(timezone.utc).date().isoformat()
            data = [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), float(p))
                    for t, p in zip(q['timestamp'], prices)
                    if p is not None and math.isfinite(p) and p > 0 and
                    datetime.fromtimestamp(t, timezone.utc).date().isoformat() < today]
            if len({d for d, p in data}) != len(data):
                raise ValueError('Duplicate daily price date')
            return data, dict(symbol=symbol, url=url, retrievedAt=datetime.now(timezone.utc).isoformat(),
                payloadHash=digest(raw), rows=len(data), firstDate=data[0][0], lastDate=data[-1][0], status='ok')
        except Exception as exc:
            if attempt:
                return [], dict(symbol=symbol, url=url, status='error', error=str(exc))
            time.sleep(.5)

def past(series, origin):
    n = bisect_left([x[0] for x in series], origin)
    return series[:n]

def own_features(series, origin):
    data = past(series, origin)
    if len(data) < 253:
        return None
    p = np.array([v for d, v in data[-253:]])
    ret = np.diff(np.log(p))
    return dict(through=data[-1][0], values=[float(np.log(p[-1]/p[-1-k])) for k in (63,126,252)]+
        [float(ret[-63:].std(ddof=1)*np.sqrt(252)), float(p[-1]/p[-200:].mean()-1),
         float(p[-1]/p[-63:].max()-1)])

def residual_features(own, market, sector, origin):
    own, market, sector = past(own, origin), past(market, origin), past(sector, origin)
    m, s = dict(market), dict(sector)
    days = [d for d, p in own if d in m]
    if len(days) < 253:
        return None
    days = days[-253:]
    a = dict(own)
    y = np.diff(np.log([a[d] for d in days]))
    mr = np.diff(np.log([m[d] for d in days]))
    has_sector = all(d in s for d in days)
    sr = np.diff(np.log([s[d] for d in days]))-mr if has_sector else np.zeros(252)
    x = np.column_stack([np.ones(252), mr, sr])
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    residual = y-x@beta
    return dict(through=days[-1], sectorAvailable=has_sector,
        values=[float(beta[1]), float(beta[2])]+[float(residual[-n:].sum()) for n in (63,126,252)])

def build_features(source, universe, histories, protocol):
    features = {}
    keys = sorted({(r['symbol'],r['origin']) for h in protocol['horizons']
                   for r in source['stocks'][str(h)]['outcomes']})
    for symbol, origin in keys:
        ticker = protocol['sectorETFs'].get(universe['members'][symbol]['sector'])
        own = own_features(histories.get(symbol, []), origin)
        market = own_features(histories.get('SPY', []), origin)
        sector = own_features(histories.get(ticker, []), origin)
        residual = residual_features(histories.get(symbol, []), histories.get('SPY', []),
                                     histories.get(ticker, []), origin)
        usable = bool(own and market and residual)
        if usable:
            absolute = own['values']+market['values'][:3]+[market['values'][4]]
            absolute += sector['values'][:3]+[sector['values'][4]] if sector else [None]*4
            relative = [own['values'][j]-market['values'][j] for j in range(3)]
            relative += [own['values'][j]-sector['values'][j] if sector else None for j in range(3)]
            relative += residual['values']
        else:
            absolute, relative = None, None
        features[symbol+'|'+origin] = dict(symbol=symbol, origin=origin, usable=usable,
            ownThrough=own['through'] if own else None, marketThrough=market['through'] if market else None,
            sectorThrough=sector['through'] if sector else None, sectorTicker=ticker,
            residualThrough=residual['through'] if residual else None,
            sectorAvailable=bool(sector and residual and residual['sectorAvailable']),
            absolute=absolute, relative=relative)
    return features

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--folder',type=Path,default=FOLDER)
    args=parser.parse_args(); folder=args.folder
    protocol=json.loads((folder/'PROTOCOL.json').read_text())
    source=json.loads(gzip.decompress((folder/'sources/environment.json.gz').read_bytes()))
    universe=json.loads((folder/'sources/universe.json').read_text())
    symbols=sorted({r['symbol'] for h in protocol['horizons'] for r in source['stocks'][str(h)]['outcomes']} |
                   {'SPY'} | set(protocol['sectorETFs'].values()))
    histories,metadata={},{}
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending={pool.submit(fetch,s):s for s in symbols}
        for i,f in enumerate(as_completed(pending),1):
            s=pending[f];histories[s],metadata[s]=f.result()
            if i%25==0 or not histories[s]: print(i,len(symbols),s,metadata[s]['status'],flush=True)
    features=build_features(source,universe,histories,protocol)
    data=dict(version=protocol['version'], collectedAt=datetime.now(timezone.utc).isoformat(),
        sourceHash=protocol['sourceHash'],protocolHash=digest((folder/'PROTOCOL.json').read_bytes()),
        extractionCodeHash=digest(Path(__file__).read_bytes()), metadata={s:metadata[s] for s in sorted(metadata)},
        features=features, rawDataVintage='Revised adjusted history, not certified point-in-time data',
        coverage=dict(rows=len(features),usable=sum(r['usable'] for r in features.values()),
            sectorAvailable=sum(r['sectorAvailable'] for r in features.values())))
    raw=json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    (folder/'sources/raw-features.json.gz').write_bytes(gzip.compress(raw,mtime=0))
    print('Frozen feature snapshot',data['coverage'],digest(raw),flush=True)

if __name__=='__main__': main()
