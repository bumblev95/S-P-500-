"""Small public homepage snapshot: independent feeds, closed sessions and existing rankings.

FRED, credit, the stock decision rules and company-news classification are read-only.
Week-to-date starts on Monday in New York and uses the last close before Monday.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo('America/New_York')
# Only collector/evaluation clocks are volatile. Source freshness timestamps
# (priceGeneratedAt/marketGeneratedAt), session dates and publication dates stay
# significant, as do all values, statuses, cache flags and error details.
POLLING_TIMESTAMPS = {'generatedAt', 'evaluatedAt', 'lastAttemptAt', 'lastSuccessAt'}
HOME_TRANSLATION_VERSION = 'home-news-ko-v2'
FEEDS = [
    ('Fed 발표', 'https://www.federalreserve.gov/feeds/press_all.xml'),
    ('Fed 연설', 'https://www.federalreserve.gov/feeds/speeches.xml'),
    ('BBC 경제', 'https://feeds.bbci.co.uk/news/business/rss.xml'),
    ('BBC 국제', 'https://feeds.bbci.co.uk/news/world/rss.xml'),
    ('CNBC 주요', 'https://www.cnbc.com/id/100003114/device/rss/rss.html'),
    ('CNBC 금융', 'https://www.cnbc.com/id/10000664/device/rss/rss.html'),
    ('CNBC 경제', 'https://www.cnbc.com/id/20910258/device/rss/rss.html'),
]
INDICES = [('^GSPC', 'S&P 500', 'chart-no-axes-combined'), ('^IXIC', '나스닥 종합', 'chart-no-axes-combined'), ('^DJI', '다우', 'chart-no-axes-combined')]
SECTORS = [('XLK','기술','cpu'),('XLC','커뮤니케이션','radio'),('XLY','경기소비재','shopping-bag'),('XLF','금융','landmark'),('XLI','산업재','factory'),('XLV','헬스케어','heart-pulse'),('XLP','필수소비재','shopping-basket'),('XLRE','부동산','house'),('XLU','유틸리티','zap'),('XLB','소재','flask-conical'),('XLE','에너지','fuel')]
MACRO = re.compile(r'\b(econom\w*|inflation|jobs|employment|central bank|interest rate|federal reserve|fed|tariff\w*|sanction\w*|war|conflict|invasion|missile|strike\w*|ceasefire|oil|energy|gas|shipping|hormuz|market\w*|stock\w*|equities|shares?|wall street|s&p(?: 500)?|nasdaq|dow|earnings?|recession|treasury|bond\w*|yield\w*|stress test|financial stability)\b',re.I)
OPINION = re.compile(r'\b(could|might|may|fear\w*|warn\w*|consider\w*|urge\w*|opinion|analysis|what if|war of words|long shot|unlikely|prepar\w*|scenario\w*|drill\w*|why|how)\b',re.I)
MAJOR = re.compile(r'\b((?:raises?|cuts?|holds?|hikes?) (?:the )?(?:interest |policy )?rates?|rate (?:cut|hike|decision)|inflation|consumer price|jobs report|payroll\w*|invades?|invasion|launches? (?:an? )?(?:attack|missile)|declares? war|ceasefire (?:agreed|signed|takes effect)|closes? (?:the )?strait|sanctions? (?:imposed|announced))\b',re.I)


def stamp(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    except (ValueError, TypeError):
        return None


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def semantic_content(value):
    """Compare JSON content without polling clocks; array order is significant."""
    if isinstance(value, dict):
        return {k:semantic_content(v) for k,v in value.items() if k not in POLLING_TIMESTAMPS}
    if isinstance(value, list):
        return [semantic_content(v) for v in value]
    return value


def publish_if_changed(root, snapshot, cache):
    """Keep both files byte-for-byte on a no-op, including their saved clocks.

    A meaningful change saves the pair together so fallback success times follow
    a published failure/recovery. Cache-only news or history changes also count.
    """
    public_path, cache_path = root/'market/home.json', root/'market/home-cache.json'
    try:
        previous = json.loads(public_path.read_text(encoding='utf-8'))
        previous_cache = json.loads(cache_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        previous = previous_cache = None
    if (semantic_content(previous) == semantic_content(snapshot)
            and semantic_content(previous_cache) == semantic_content(cache)):
        return previous, False
    atomic(public_path, snapshot)
    atomic(cache_path, cache)
    return snapshot, True


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 S-P-500 public market briefing','Accept':'application/json, application/xml, text/html;q=0.9,*/*;q=0.5'})
    with urllib.request.urlopen(req,timeout=12) as response:
        data = response.read(3*1024*1024+1)
        if len(data)>3*1024*1024: raise ValueError('Response too large')
        return data.decode('utf-8',errors='replace')


def week_bounds(now):
    local = now.astimezone(NY)
    start = local.date()-timedelta(days=local.weekday())
    return start, start+timedelta(days=4)


def closed_rows(payload, now):
    result = payload['chart']['result'][0]
    values = result['indicators']['quote'][0]['close']
    rows = {}
    local = now.astimezone(NY)
    for ts, close in zip(result.get('timestamp',[]),values):
        if not isinstance(close,(float,int)) or not math.isfinite(close) or close<=0: continue
        session = datetime.fromtimestamp(ts,timezone.utc).astimezone(NY).date()
        if session>local.date(): continue
        if session==local.date():
            observed = datetime.fromtimestamp(result.get('meta',{}).get('regularMarketTime',0),timezone.utc).astimezone(NY)
            if local.time()<time(16,15) or observed.date()!=session or observed.time()<time(16): continue
        rows[session.isoformat()] = {'date':session.isoformat(),'close':float(close)}
    return sorted(rows.values(),key=lambda q:q['date'])


def returns(rows, now):
    start, end = week_bounds(now)
    if len(rows)<2: raise ValueError('Two closed observations required')
    last, previous = rows[-1], rows[-2]
    baseline = next((q for q in reversed(rows) if q['date']<start.isoformat()),None)
    in_week = start.isoformat()<=last['date']<=end.isoformat()
    weekly = (last['close']/baseline['close']-1)*100 if baseline and in_week else None
    return {'asOf':last['date'],'close':last['close'],'day':(last['close']/previous['close']-1)*100,
            'dayBaseDate':previous['date'],'week':weekly,'weekBaseDate':baseline['date'] if baseline and in_week else None}


def prices(prior, now, fetch=get):
    old = prior.get('quotes',{})
    quotes, cache = {}, {}
    def collect(spec):
        symbol,name,icon=spec
        error=None
        for host in ['query1.finance.yahoo.com','query2.finance.yahoo.com']:
            try:
                url='https://'+host+'/v8/finance/chart/'+urllib.parse.quote(symbol,safe='')+'?range=1mo&interval=1d'
                rows=closed_rows(json.loads(fetch(url)),now)
                values=returns(rows,now)
                return symbol,{'symbol':symbol,'name':name,'icon':icon,**values,'status':'ready','fromCache':False,'lastSuccessAt':now.isoformat(),'lastAttemptAt':now.isoformat()},rows
            except Exception as exc: error=type(exc).__name__
        previous=old.get(symbol,{})
        rows=previous.get('rows',[])
        try:
            safe=[q for q in rows if isinstance(q,dict) and stamp(q.get('date')) and stamp(q['date']).date()<=now.astimezone(NY).date() and isinstance(q.get('close'),(float,int)) and math.isfinite(q['close']) and q['close']>0]
            values=returns(sorted(safe,key=lambda q:q['date']),now)
            valid=(now.astimezone(NY).date()-date.fromisoformat(values['asOf'])).days<=5
        except (ValueError,TypeError,KeyError): values={}; valid=False
        q={'symbol':symbol,'name':name,'icon':icon,**(values if valid else {}),'status':'unavailable','fromCache':valid,'lastSuccessAt':previous.get('lastSuccessAt'),'lastAttemptAt':now.isoformat(),'error':error}
        return symbol,q,rows if valid else []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(collect,spec) for spec in INDICES+SECTORS]
        for future in as_completed(futures):
            symbol,q,rows=future.result();quotes[symbol]=q
            cache[symbol]={'rows':rows,'lastSuccessAt':q['lastSuccessAt']}
    # Persist cache blocks in spec order, independent of worker completion.
    return quotes,{symbol:cache[symbol] for symbol,_,_ in INDICES+SECTORS}


class Text(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.skip+=1
        if not self.skip and tag in ('p','br','div','h1','h2','h3'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
        if not self.skip and tag in ('p','div','h1','h2','h3'): self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)
    def text(self):
        return '\n'.join(re.sub(r'\s+',' ',p).strip() for p in ''.join(self.parts).split('\n') if p.strip())


def plain(value):
    parser=Text();parser.feed(value or '');return parser.text()


def allowed(url):
    try:
        u=urllib.parse.urlsplit(url)
        return u.scheme=='https' and u.hostname in {'www.federalreserve.gov','www.bbc.com','www.bbc.co.uk','bbc.com','bbc.co.uk','www.cnbc.com','cnbc.com'} and not u.username and not u.password
    except ValueError:return False


def category(text):
    if re.search(r'\b(war|conflict|invasion|missile|ceasefire|sanction|hormuz)\b',text,re.I):return '전쟁·국제'
    if re.search(r'\b(oil|energy|gas|shipping)\b',text,re.I):return '유가·원자재'
    if re.search(r'\b(fed|federal reserve|monetary|interest rate|treasury|bond|yield|stress test)\b',text,re.I):return 'Fed·금리'
    if re.search(r'\b(stock\w*|equities|shares?|wall street|s&p(?: 500)?|nasdaq|dow|earnings?)\b',text,re.I):return '주식시장'
    return '경제·물가'


def parse_feed(xml, source, now):
    articles=[]
    for item in ET.fromstring(xml).findall('.//item'):
        title=plain(item.findtext('title'));url=(item.findtext('link') or '').strip()
        try: published=parsedate_to_datetime(item.findtext('pubDate')).astimezone(timezone.utc)
        except (ValueError,TypeError,AttributeError): continue
        age=(now-published).total_seconds()
        if not title or not allowed(url) or not 0<=age<=14*86400:continue
        if not MACRO.search(title):continue
        excerpt=plain(item.findtext('description'))
        articles.append({'url':url,'title':title,'publishedAt':published.isoformat(),'firstPublishedAt':published.isoformat(),'source':source,
                         'category':category(title),'_excerpt':excerpt,'lastSuccessAt':now.isoformat(),'fromCache':False,'sourceStatus':'ready'})
    return articles


def retain_news(articles, source, now):
    kept=[]
    for item in articles:
        pub=stamp(item.get('publishedAt'))
        if item.get('source')==source and allowed(item.get('url','')) and pub and 0<=(now-pub).total_seconds()<=14*86400:
            old=deepcopy(item);old.update(fromCache=True,sourceStatus='unavailable');kept.append(old)
    return kept


def passage(article, body):
    if article['source'].startswith('Fed'):
        paragraphs=[p for p in plain(body).split('\n') if 50<=len(p)<=1800]
        relevant=[p for p in paragraphs if re.search(r'\b(inflation|FOMC|interest|stress test|capital requirements)\b',p,re.I)]
        if not relevant:raise ValueError('No substantive source paragraph')
        def priority(p):
            return 3*bool(re.search(r'FOMC.{0,80}(voted|decided)',p,re.I))+2*bool(re.search(r'inflation.{0,80}(risk|target|percent)',p,re.I))+bool(re.search(r'(finalized|final rule|capital)',p,re.I))
        paragraph=max(relevant,key=priority)
    else:paragraph=article.get('_excerpt') or article['title']
    sentences=re.split(r'(?<=[.!?])\s+',paragraph)
    lead=next((s for s in sentences if 35<=len(s)<=500),article['title'])
    return lead


def collect_news(prior, now, reviewed, fetch=get):
    articles=[];feeds=[];old_items=prior.get('news',[])
    old_by_url={a['url']:a for a in old_items if isinstance(a,dict) and a.get('url')}
    old_feeds={f['name']:f for f in prior.get('feeds',[]) if isinstance(f,dict) and f.get('name')}
    def collect(spec):
        source,url=spec;before=old_feeds.get(source,{})
        try:
            items=parse_feed(fetch(url),source,now)
            return items,{'name':source,'url':url,'status':'ready','lastAttemptAt':now.isoformat(),'lastSuccessAt':now.isoformat(),'fromCache':False}
        except Exception as exc:
            return retain_news(old_items,source,now),{'name':source,'url':url,'status':'unavailable','lastAttemptAt':now.isoformat(),'lastSuccessAt':before.get('lastSuccessAt'),'fromCache':True,'error':type(exc).__name__}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for items,feed in pool.map(collect,FEEDS):articles.extend(items);feeds.append(feed)
    # The same CNBC story can appear in several section feeds. Translate and rank it once.
    unique={}
    for item in articles:
        unique.setdefault(item['url'],item)
    articles=list(unique.values())
    # A recurring URL retains its first publication time; polling cannot restart breaking news.
    for item in articles:
        previous=old_by_url.get(item['url'],{})
        first=stamp(previous.get('firstPublishedAt') or previous.get('publishedAt'))
        if first and first<=stamp(item['publishedAt']):item['firstPublishedAt']=first.isoformat()
        if not item['fromCache']:
            title=item['title']
            item['importance']='important' if MAJOR.search(title) and not OPINION.search(title) else 'normal'
            item['importanceReason']='주요 경제지표·정책 또는 국제 사건 보도' if item['importance']=='important' else ''
    # Recency drives the homepage. Importance is a badge, not a pin that can
    # keep older stories above newer market updates.
    ordered=sorted(articles,key=lambda a:(a['publishedAt'],a['importance']=='important'),reverse=True)
    candidates=[item for index,item in enumerate(ordered) if index<12 or item['url'] in reviewed]
    for item in candidates:
        if item['fromCache']:continue
        previous=old_by_url.get(item['url'],{})
        try:
            body=fetch(item['url']) if item['source'].startswith('Fed') else ''
            lead=passage(item,body)
            digest=sha256((item['title']+'\n'+lead).encode()).hexdigest()
            item['sourceHash']=digest
            item['sourceExcerpt']=lead
            review=reviewed.get(item['url'],{})
            text=plain(body) if body else item.get('_excerpt','')
            checked=(review.get('title')==item['title'] and ((review.get('sourceHash')==digest) or (review.get('evidence') and all(e.lower() in text.lower() for e in review['evidence']))))
            if checked:
                item.update(headlineKo=review['headline'],summaryKo=review['summary'],translationStatus='ready',translationMethod='reviewed-summary',translationVersion=HOME_TRANSLATION_VERSION,importance=review.get('importance','normal'),importanceReason=review.get('importanceReason',''))
            elif previous.get('sourceHash')==digest and previous.get('translationStatus')=='ready' and previous.get('translationVersion')==HOME_TRANSLATION_VERSION:
                for key in ['headlineKo','summaryKo','translationStatus','translationMethod','translationVersion']:item[key]=previous[key]
            else:item['_translate']=[item['title'],lead]
        except Exception as exc:
            if previous.get('title')==item['title'] and previous.get('translationStatus')=='ready':
                for key in ['headlineKo','summaryKo','translationStatus','translationMethod','translationVersion','sourceHash','importance','importanceReason']:item[key]=previous.get(key)
                item.update(fromCache=True,sourceStatus='unavailable',lastSuccessAt=previous.get('lastSuccessAt'))
            else:item['translationStatus']='unavailable'
            item['summaryError']=type(exc).__name__
    return ordered,feeds


def translate_news(articles, root, translate=None):
    tasks=[a for a in articles if a.get('_translate')]
    if tasks:
        if translate is None:
            from translate_company_news import engine, verify_engine
            translate=engine(root/'research/source-cache/home-news-ko/model')
            verify_engine(translate)
        from translate_company_news import valid_korean
        texts=[p for a in tasks for p in a['_translate']]
        outputs=translate(texts)
        if len(outputs)!=len(texts):raise ValueError('Translation count mismatch')
        for index,item in enumerate(tasks):
            headline,summary=outputs[index*2:index*2+2]
            item.update(headlineKo=headline,summaryKo=summary,translationStatus='ready' if all(valid_korean(s) for s in [headline,summary]) else 'unavailable',translationMethod='machine-translation',translationVersion=HOME_TRANSLATION_VERSION)
    for item in articles:
        item.pop('_translate',None);item.pop('_excerpt',None)
    return articles


def assemble(quotes, news, feeds, rankings, now):
    start,end=week_bounds(now)
    dated=[q['asOf'] for q in quotes.values() if q.get('asOf')]
    asof=max(dated,default=None)
    complete=bool(asof and asof==end.isoformat() and (now.astimezone(NY).date()>end or now.astimezone(NY).time()>=time(16,15)))
    available=[q for q in quotes.values() if q.get('day') is not None and q.get('asOf')==asof and q['symbol'].startswith('XL')]
    if available:
        high=max(available,key=lambda q:q['day']);low=min(available,key=lambda q:q['day'])
        brief=high['name']+' 강세 · '+low['name']+' 약세' if high['day']>0>low['day'] else ('섹터 전반 상승' if low['day']>0 else '섹터 전반 하락' if high['day']<0 else '섹터 혼조')
    else:brief='시장 마감 자료 확인 중'
    seen=set();selected=[]
    for item in sorted(news,key=lambda a:(a['publishedAt'],a.get('importance')=='important'),reverse=True):
        # Identical event headlines from two sources do not fill the briefing twice.
        key=re.sub(r'\W','',item.get('headlineKo','')).lower()
        if item.get('translationStatus')!='ready' or key in seen:continue
        seen.add(key);selected.append({k:v for k,v in item.items() if k!='sourceExcerpt'})
        if len(selected)==5:break
    return {'schemaVersion':1,'generatedAt':now.isoformat(),'rankings':rankings,'brief':brief,
            'recap':{'asOf':asof,'weekStart':start.isoformat(),'weekEnd':end.isoformat(),'weekComplete':complete,'timezone':'America/New_York','method':'sector-etf-unadjusted-close-price-return',
                     'indices':[quotes[s] for s,_,_ in INDICES],'sectors':[quotes[s] for s,_,_ in SECTORS]},
            'news':selected,'feeds':feeds,'newsPolicy':{'maxAgeDays':14,'breakingMaxAgeHours':2,'displayOrder':'latest-first','importanceBasis':'source-event-and-reviewed-context'}}


def home_rankings(root, now):
    return json.loads(subprocess.check_output(
        ['node',str(root/'scripts/build_home_rankings.cjs'),str(root),now.isoformat()],text=True))


def refresh_rankings(root=ROOT, now=None):
    """Publish the daily ranking without waiting for external news or models."""
    now=now or datetime.now(timezone.utc)
    path=root/'market/home.json'
    previous=json.loads(path.read_text(encoding='utf-8'))
    snapshot={**previous,'rankings':home_rankings(root,now),'generatedAt':now.isoformat()}
    changed=semantic_content(previous)!=semantic_content(snapshot)
    if changed:atomic(path,snapshot)
    else:snapshot=previous
    print(json.dumps({'attemptedAt':now.isoformat(),'changed':changed,'rankingsAsOf':snapshot['rankings'].get('asOf'),
                      'buy':[a['symbol'] for a in snapshot['rankings']['buy']],
                      'sell':[a['symbol'] for a in snapshot['rankings']['sell']]},ensure_ascii=False),flush=True)
    return snapshot


def build(root=ROOT, now=None, fetch=get, translate=None, translate_enabled=True):
    now=now or datetime.now(timezone.utc)
    path=root/'market/home-cache.json'
    prior=json.loads(path.read_text()) if path.exists() else {}
    reviewed_path=root/'market/home-reviewed-news.json'
    reviewed=json.loads(reviewed_path.read_text()) if reviewed_path.exists() else {}
    rankings=home_rankings(root,now)
    quotes,price_cache=prices(prior,now,fetch)
    articles,feeds=collect_news(prior,now,reviewed,fetch)
    if translate_enabled:
        try:translate_news(articles,root,translate)
        except Exception as exc:
            # Translation availability cannot erase verified summaries or price data.
            for item in articles:
                if item.get('_translate'):item.update(translationStatus='unavailable',summaryError=type(exc).__name__)
                item.pop('_translate',None);item.pop('_excerpt',None)
    else:
        for item in articles:item.pop('_translate',None);item.pop('_excerpt',None)
    snapshot=assemble(quotes,articles,feeds,rankings,now)
    snapshot,changed=publish_if_changed(root,snapshot,{'quotes':price_cache,'news':articles,'feeds':feeds})
    print(json.dumps({'attemptedAt':now.isoformat(),'changed':changed,'generatedAt':snapshot['generatedAt'],'asOf':snapshot['recap']['asOf'],'buy':[a['symbol'] for a in rankings['buy']],'sell':[a['symbol'] for a in rankings['sell']],
                      'readyQuotes':sum(q['status']=='ready' for q in quotes.values()),'news':len(snapshot['news']),'feeds':[{k:f[k] for k in ['name','status']} for f in feeds]},ensure_ascii=False),flush=True)
    return snapshot


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-translate',action='store_true')
    parser.add_argument('--rankings-only',action='store_true')
    args=parser.parse_args()
    if args.rankings_only:refresh_rankings()
    else:build(translate_enabled=not args.no_translate)
