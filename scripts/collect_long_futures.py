"""Checksum-verified public monthly archives, kept separate from live venue data."""
import csv,hashlib,io,json,math,os,threading,zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
from collect_simulation_data import valid

ROOT=Path(__file__).resolve().parents[1]
CACHE=Path(os.environ.get('PAPER_LONG_CACHE','/tmp/paper-long-cache'))
BASE='https://data.binance.vision/'
LIST='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?'
STOP=threading.Event()

def read(url):
    if STOP.is_set():raise RuntimeError('Archive host access/rate limit; collection stopped')
    try:
        with urlopen(url,timeout=30) as response:return response.read()
    except HTTPError as exc:
        if exc.code in (401,403,429):STOP.set()
        raise

def listing(prefix):
    keys=[];marker=None
    while True:
        q={'prefix':prefix}
        if marker:q['marker']=marker
        root=ET.fromstring(read(LIST+urlencode(q)))
        page=[x.text for x in root.iter() if x.tag.endswith('}Key')]
        keys.extend(k for k in page if k.endswith('.zip'))
        more=next((x.text for x in root.iter() if x.tag.endswith('}IsTruncated')),'false')
        if more!='true':return sorted(keys)
        if not page:raise ValueError('Archive listing did not advance')
        marker=page[-1]

def archive(key):
    dest=CACHE/'zips'/key;check=Path(str(dest)+'.CHECKSUM')
    dest.parent.mkdir(parents=True,exist_ok=True)
    if not check.exists():check.write_bytes(read(BASE+key+'.CHECKSUM'))
    expected=check.read_text().split()[0]
    if not dest.exists():
        value=read(BASE+key)
        if hashlib.sha256(value).hexdigest()!=expected:raise ValueError('Checksum mismatch '+key)
        tmp=Path(str(dest)+'.tmp');tmp.write_bytes(value);tmp.replace(dest)
    value=dest.read_bytes()
    if hashlib.sha256(value).hexdigest()!=expected:raise ValueError('Cached checksum mismatch '+key)
    with zipfile.ZipFile(io.BytesIO(value)) as z:
        names=z.namelist()
        if len(names)!=1:raise ValueError('Unexpected archive members')
        rows=list(csv.reader(io.StringIO(z.read(names[0]).decode('utf-8-sig'))))
    return key,expected,rows

def collect():
    CACHE.mkdir(parents=True,exist_ok=True);now=datetime.now(timezone.utc);month=now.strftime('%Y-%m')
    jobs=[]
    for coin in ('BTC','ETH','SOL'):
        for kind in ('klines','fundingRate'):
            prefix=f'data/futures/um/monthly/{kind}/{coin}USDT/'+('15m/' if kind=='klines' else '')
            jobs.extend((coin,kind,key) for key in listing(prefix) if key[-11:-4]<month)
    market={'generatedAt':now.isoformat(),'crypto':{},'stocks':{},'errors':[],'venue':'Binance USD-M archive'}
    buckets={c:{'bars':{},'funding':{},'invalid':0} for c in ('BTC','ETH','SOL')};files=[]
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures={pool.submit(archive,key):(coin,kind) for coin,kind,key in jobs}
        for i,f in enumerate(as_completed(futures),1):
            coin,kind=futures[f]
            try:key,checksum,rows=f.result()
            except Exception as exc:
                market['errors'].append(coin+' '+kind+': '+str(exc));continue
            files.append({'key':key,'sha256':checksum,'rows':len(rows)})
            for values in rows:
                if not values or not values[0].isdigit():continue
                try:
                    if kind=='klines':
                        t=int(values[0]);end=int(values[6])
                        if t>10**14:t//=1000;end//=1000
                        r=dict(t=t,end=end,open=float(values[1]),high=float(values[2]),low=float(values[3]),close=float(values[4]),volume=float(values[5]))
                        if not valid(r) or t%900000 or end!=t+899999:raise ValueError('Invalid 15-minute candle')
                        old=buckets[coin]['bars'].get(t)
                        if old and old!=r:raise ValueError('Conflicting duplicate candle')
                        buckets[coin]['bars'][t]=r
                    else:
                        t=int(values[0]);interval=float(values[1]);rate=float(values[2])
                        if not math.isfinite(rate) or not 0<interval<=24:raise ValueError('Invalid funding')
                        buckets[coin]['funding'][t]={'time':t,'rate':rate,'intervalHours':interval}
                except (ValueError,IndexError):buckets[coin]['invalid']+=1
            if i%40==0:print('Verified archives',i,'/',len(jobs),flush=True)
    coverage={}
    for coin,b in buckets.items():
        rows=sorted(b['bars'].values(),key=lambda r:r['t']);funding=sorted(b['funding'].values(),key=lambda r:r['time'])
        if not rows or not funding:raise ValueError(coin+' missing candle/funding history')
        groups={}
        for r in rows:groups.setdefault(r['t']//3600000,[]).append(r)
        hourly=[]
        for hour,g in sorted(groups.items()):
            if len(g)!=4 or g[0]['t']!=hour*3600000 or any(r['t']!=g[0]['t']+i*900000 for i,r in enumerate(g)):continue
            hourly.append(dict(t=g[0]['t'],end=g[-1]['end'],open=g[0]['open'],high=max(r['high'] for r in g),low=min(r['low'] for r in g),close=g[-1]['close'],volume=sum(r['volume'] for r in g)))
        gaps=sum(max(0,(r['t']-rows[i-1]['t'])//900000-1) for i,r in enumerate(rows) if i)
        market['crypto'][coin]={'frames':{'15m':rows,'1h':hourly},'funding':funding,'fundingSchedule':'published','source':'Binance USD-M monthly archive; distinct from Hyperliquid','errors':[]}
        coverage[coin]={'start':rows[0]['t'],'end':rows[-1]['end'],'bars':len(rows),'hours':len(hourly),'fundingEvents':len(funding),'missingBars':gaps,'invalidRows':b['invalid']}
    manifest={'generatedAt':now.isoformat(),'source':BASE,'coverage':coverage,'files':sorted(files,key=lambda x:x['key']),'errors':market['errors']}
    (CACHE/'market.json').write_text(json.dumps(market,separators=(',',':')))
    (CACHE/'manifest.json').write_text(json.dumps(manifest,separators=(',',':')))
    print(json.dumps({'coverage':coverage,'errors':market['errors'],'archives':len(files)},indent=2),flush=True)
    return manifest

if __name__=='__main__':collect()
