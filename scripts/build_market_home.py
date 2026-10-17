"""Small public homepage snapshot: independent feeds, closed sessions and existing rankings.

FRED, credit, the stock decision rules and company-news classification are read-only.
Week-to-date starts on Monday in New York and uses the last close before Monday.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
import errno
from hashlib import sha256
from html.parser import HTMLParser
from http.client import IncompleteRead
import json
import math
from pathlib import Path
import re
import socket
import subprocess
from time import sleep
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from translate_company_news import valid_korean, valid_korean_headline, valid_korean_summary, simpler_headline_input
from market_news_events import group_coverage, VERSION as EVENT_DEDUPLICATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo('America/New_York')
# Only collector/evaluation clocks are volatile. Source freshness timestamps
# (priceGeneratedAt/marketGeneratedAt), session dates and publication dates stay
# significant, as do all values, statuses, cache flags and error details.
POLLING_TIMESTAMPS = {'generatedAt', 'evaluatedAt', 'lastAttemptAt', 'lastSuccessAt'}
# Revalidate cached headlines in place; a version bump would retranslate healthy v2 summaries.
HOME_TRANSLATION_VERSION = 'home-news-ko-v2'
HEADLINE_QUALITY_VERSION = 'home-headline-quality-v3'
TRANSLATION_FIELDS = ('headlineKo', 'summaryKo', 'translationStatus', 'translationMethod', 'translationVersion', 'headlineFallbackVersion')
FEED_RETRY_DELAYS = (0.5, 1.0)  # At most three requests, with 1.5s total backoff.
FEED_RETRY_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
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
# Collection and display share one topic decision. In particular, an ambiguous
# strike, political name or generic "market" is not economic evidence by itself.
MONETARY = re.compile(r'\b((?-i:Fed|FED)|federal reserve|federal open market committee|FOMC|central bank\w*|bank of (?:england|japan|canada)|monetary|interest rates?|treasury|bonds?|bond yields?|stress tests?|financial stability)\b',re.I)
EQUITY = re.compile(r'\b(stocks?|stock market|equities|share prices?|shares? (?:rise|fall|drop|jump|surge|slide)|wall street|s&p(?: 500)?|nasdaq|dow|earnings?|IPOs?|mergers?)\b',re.I)
ECONOMY = re.compile(r'\b(econom\w*|inflation|deflation|recession|GDP|global (?:growth|slowdown)|consumer prices?|cost.of.living|payroll\w*|unemployment|employment|wages?|jobs report|job cuts?|shed [\d,]+ jobs|budget\w*|deficits?|sovereign debt|trade deficit)\b',re.I)
COMMODITY = re.compile(r'\b(oil|crude|energy|natural gas|gas prices?|fuel|diesel|refiner\w*|shipping|supply chains?|exports?|imports?)\b',re.I)
TRADE = re.compile(r'\b(tariffs?|trade (?:talks?|deals?|agreements?|war|wars|restrictions?)|export controls?|economic sanctions?|market access)\b',re.I)
SANCTIONS = re.compile(r'\bsanctions?\b',re.I)
SANCTION_CONTEXT = re.compile(r'\b(imposed|imposes?|lifted|lifts?|economic|trade|bank\w*|asset\w*|exports?|imports?|Russia|Iran|China|North Korea)\b',re.I)
FINANCE = re.compile(r'\b(financial markets?|bull market|bear market|prediction markets?|derivatives|real estate market|investors?|investments?|banking|bank taxes|private equity|hedge funds?)\b',re.I)
LABOR = re.compile(r'\b(workers?|unions?|labor|labour|wages?|pay dispute|industrial action)\b',re.I)
STRIKE = re.compile(r'\b(strikes?|striking|struck)\b',re.I)
MILITARY = re.compile(r'\b(wars?|invasion|missiles?|airstrikes?|air strikes?|drone (?:attacks?|strikes?)|retaliatory strikes?|military|bombing|ceasefire|armed conflict)\b',re.I)
CONFLICT_ACTOR = re.compile(r'\b(Ukraine|Ukrainian|Russia|Russian|Zelensky|Putin|Houthi\w*|Iran|Iranian|Israel|Israeli|Gaza)\b',re.I)
ATTACK = re.compile(r'\b(attacks?|attacking|strikes?|striking|struck)\b',re.I)
CHOKEPOINT = re.compile(r'\b(hormuz|suez|red sea)\b',re.I)
CHOKEPOINT_EVENT = re.compile(r'\b(clos\w*|block\w*|disrupt\w*|reopen\w*|halt\w*)\b',re.I)
FIGURATIVE_WAR = re.compile(r'\b(?:trade|price|bidding) wars?\b|\bwar of words\b',re.I)
STRIKE_IDIOM = re.compile(r'\b(?:strikes?|struck|striking) (?:a |an |the |new )?(?:trade |wage |pay |oil |energy |gas )?(?:deals?|agreements?|balance|chord|pose)\b',re.I)
PHYSICAL_STOCK = re.compile(r'\b(?:oil|crude|diesel|fuel|gas|weapons?|missiles?|arms|ammunition|food|inventory) stocks?\b|\bstocks? of (?:oil|crude|diesel|fuel|gas|weapons?|missiles?|arms|ammunition|food)\b',re.I)
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


def retryable_feed_error(error):
    # HTTPError is also a URLError: classify its status before unwrapping reason.
    if isinstance(error, urllib.error.HTTPError):
        return error.code in FEED_RETRY_HTTP_STATUSES
    if isinstance(error, urllib.error.URLError):
        error = error.reason
    return (isinstance(error, (TimeoutError, ConnectionError, IncompleteRead))
            or isinstance(error, socket.gaierror) and error.errno == socket.EAI_AGAIN
            or isinstance(error, OSError) and error.errno in {errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH})


def fetch_feed(url, fetch):
    """Retry transient transport failures only; parsing and cache policy stay outside."""
    for attempt in range(len(FEED_RETRY_DELAYS) + 1):
        try:
            return fetch(url)
        except (OSError, IncompleteRead) as exc:
            if not retryable_feed_error(exc) or attempt == len(FEED_RETRY_DELAYS):
                raise
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            sleep(FEED_RETRY_DELAYS[attempt])


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


def military_event(text):
    # Explicit military wording survives mixed military/labor reports. An actor
    # plus an otherwise ambiguous strike needs absence of labor context.
    # Spaces preserve offsets when comparing a conflict with the leading topic.
    text=STRIKE_IDIOM.sub(lambda m:' '*len(m[0]),FIGURATIVE_WAR.sub(lambda m:' '*len(m[0]),text))
    matches=[MILITARY.search(text)]
    if CONFLICT_ACTOR.search(text) and not LABOR.search(text):matches.append(ATTACK.search(text))
    return min((m for m in matches if m),key=lambda m:m.start(),default=None)


def category(title, excerpt=''):
    """Return an evidenced topic, or None to exclude from the market briefing.

    English source fields determine relevance, never translated wording or the
    feed's section name. Prefer the title's topic; use the excerpt to resolve an
    ambiguous title or establish economic consequences of a conflict.
    """
    # Ignore the inventory sense of stock only for topic matching. Keep the
    # commodity noun, and never alter stored sources or translation inputs.
    title=PHYSICAL_STOCK.sub(lambda m:re.sub(r'\bstocks?\b','',m[0],flags=re.I),title)
    excerpt=PHYSICAL_STOCK.sub(lambda m:re.sub(r'\bstocks?\b','',m[0],flags=re.I),excerpt)
    text=title+'\n'+excerpt
    labor=bool((STRIKE.search(STRIKE_IDIOM.sub('',text)) and LABOR.search(text)) or re.search(r'\bindustrial action\b',text,re.I))
    trade=bool(TRADE.search(text) or (SANCTIONS.search(text) and SANCTION_CONTEXT.search(text)))
    chokepoint=bool(CHOKEPOINT.search(text) and CHOKEPOINT_EVENT.search(text))
    economic=any(rule.search(text) for rule in (MONETARY,EQUITY,ECONOMY,COMMODITY,FINANCE)) or labor or trade or chokepoint
    if not economic:return None
    title_topics=[m for rule in (MONETARY,EQUITY,ECONOMY,COMMODITY,FINANCE,TRADE) if (m:=rule.search(title))]
    # Sanctions are an explicit title topic too. A historical invasion in the
    # excerpt must not override a headline about waiving economic restrictions.
    if SANCTION_CONTEXT.search(text) and (sanction:=SANCTIONS.search(title)):
        title_topics.append(sanction)
    event=military_event(title)
    if ((event and not any(m.start()<event.start() for m in title_topics))
            or (not title_topics and military_event(text) and not LABOR.search(title))
            or (CHOKEPOINT.search(title) and (COMMODITY.search(text) or chokepoint))):
        return '전쟁·국제'
    # A labor-led story stays about employment even if its description also
    # reports a separate attack. "Strikes a deal"/"striking gains" are not labor.
    if STRIKE.search(title) and LABOR.search(title):return '경제·물가'
    for field in (title,excerpt):
        if MONETARY.search(field):return 'Fed·금리'
        if EQUITY.search(field):return '주식시장'
        if TRADE.search(field) or (SANCTIONS.search(field) and SANCTION_CONTEXT.search(text)):return '국제경제'
        if ECONOMY.search(field):return '경제·물가'
        if COMMODITY.search(field):return '유가·원자재'
        if FINANCE.search(field):return '금융·시장'
    return '경제·물가' if labor else None


def parse_feed(xml, source, now):
    articles=[]
    for item in ET.fromstring(xml).findall('.//item'):
        title=plain(item.findtext('title'));url=(item.findtext('link') or '').strip()
        try: published=parsedate_to_datetime(item.findtext('pubDate')).astimezone(timezone.utc)
        except (ValueError,TypeError,AttributeError): continue
        age=(now-published).total_seconds()
        if not title or not allowed(url) or not 0<=age<=14*86400:continue
        excerpt=plain(item.findtext('description'))
        topic=category(title,excerpt)
        if topic is None:continue
        articles.append({'url':url,'title':title,'publishedAt':published.isoformat(),'firstPublishedAt':published.isoformat(),'source':source,
                         'category':topic,'_excerpt':excerpt,'lastSuccessAt':now.isoformat(),'fromCache':False,'sourceStatus':'ready'})
    return articles


def retain_news(articles, source, now):
    kept=[]
    for item in articles:
        pub=stamp(item.get('publishedAt'))
        if item.get('source')==source and allowed(item.get('url','')) and pub and 0<=(now-pub).total_seconds()<=14*86400:
            topic=category(item.get('title',''),item.get('sourceExcerpt',''))
            if topic is None:continue
            old=deepcopy(item);old.update(category=topic,fromCache=True,sourceStatus='unavailable');kept.append(old)
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


def usable_translation(item):
    """A source-title fallback is displayable, but is never a ready Korean title."""
    if not valid_korean_summary(item.get('summaryKo'), item.get('sourceExcerpt', ''), item.get('title', '')): return False
    if item.get('translationStatus') == 'ready':
        return valid_korean_headline(item.get('headlineKo'), item['title'], item.get('sourceExcerpt', ''))
    return item.get('translationStatus') == 'headline-fallback' and item.get('headlineKo') == item.get('title')


def reusable_translation(item):
    # An availability fallback remains retryable; only a completed quality retry
    # can be reused without another model call for this source/version.
    return usable_translation(item) and (item.get('translationStatus')=='ready'
                                        or item.get('headlineFallbackVersion')==HEADLINE_QUALITY_VERSION)


def set_translation(item, headline, summary, fallback_checked=False):
    good_headline, good_summary = valid_korean_headline(headline, item['title'], item.get('sourceExcerpt', '')), valid_korean_summary(summary, item.get('sourceExcerpt', ''), item['title'])
    item.update(headlineKo=headline if good_headline else item['title'], summaryKo=summary,
                translationStatus=('ready' if good_headline else 'headline-fallback') if good_summary else 'unavailable',
                translationMethod=item.get('translationMethod') or 'machine-translation',
                translationVersion=HOME_TRANSLATION_VERSION)
    item.pop('headlineFallbackVersion',None)
    if not good_headline and good_summary and fallback_checked:
        item['headlineFallbackVersion']=HEADLINE_QUALITY_VERSION


def prepare_translations(articles):
    # Validate retained feed/error caches too, not only freshly fetched articles.
    # A disabled/unavailable model must still leave a safe display title.
    for item in articles:
        if (item.get('translationStatus') in ('ready','headline-fallback','unavailable')
                and ('headlineKo' in item or 'summaryKo' in item) and not reusable_translation(item)):
            item.setdefault('_translate', [None if valid_korean_headline(item.get('headlineKo'), item['title'], item.get('sourceExcerpt', '')) else item['title'],
                                           None if valid_korean_summary(item.get('summaryKo'), item.get('sourceExcerpt', ''), item['title']) else item.get('sourceExcerpt', item['title'])])
        if item.get('_translate') and ('headlineKo' in item or 'summaryKo' in item):
            set_translation(item, item.get('headlineKo'), item.get('summaryKo', ''))


def collect_news(prior, now, reviewed, fetch=get):
    articles=[];feeds=[];old_items=prior.get('news',[])
    old_by_url={a['url']:a for a in old_items if isinstance(a,dict) and a.get('url')}
    old_feeds={f['name']:f for f in prior.get('feeds',[]) if isinstance(f,dict) and f.get('name')}
    def collect(spec):
        source,url=spec;before=old_feeds.get(source,{})
        try:
            items=parse_feed(fetch_feed(url,fetch),source,now)
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
            elif previous.get('sourceHash')==digest and previous.get('translationVersion')==HOME_TRANSLATION_VERSION:
                for key in TRANSLATION_FIELDS:
                    if key in previous:item[key]=previous[key]
                if not reusable_translation(previous):
                    item['_translate']=[None if valid_korean_headline(previous.get('headlineKo'), item['title'], lead) else item['title'],
                                        None if valid_korean_summary(previous.get('summaryKo'), lead, item['title']) else lead]
            else:item['_translate']=[item['title'],lead]
        except Exception as exc:
            if previous.get('title')==item['title'] and previous.get('translationStatus') in ('ready','headline-fallback'):
                for key in (*TRANSLATION_FIELDS,'sourceHash','sourceExcerpt','importance','importanceReason'):item[key]=previous.get(key)
                item.update(fromCache=True,sourceStatus='unavailable',lastSuccessAt=previous.get('lastSuccessAt'))
            else:item['translationStatus']='unavailable'
            item['summaryError']=type(exc).__name__
    prepare_translations(ordered)
    return ordered,feeds


def translate_news(articles, root, translate=None):
    prepare_translations(articles)
    tasks=[a for a in articles if a.get('_translate')]
    if tasks:
        if translate is None:
            from translate_company_news import engine, verify_engine
            translate=engine(root/'research/source-cache/home-news-ko/model')
            verify_engine(translate)
        queries=[(index,field,text) for index,a in enumerate(tasks) for field,text in enumerate(a['_translate']) if text is not None]
        texts=[text for _,_,text in queries]
        outputs=translate(texts)
        if len(outputs)!=len(texts):raise ValueError('Translation count mismatch')
        values=[[a.get('headlineKo'),a.get('summaryKo','')] for a in tasks]
        for (index,field,_),output in zip(queries,outputs):values[index][field]=output
        retry=[index for index,(headline,_) in enumerate(values) if not valid_korean_headline(headline, tasks[index]['title'], tasks[index].get('sourceExcerpt', ''))]
        retry_complete=False
        if retry:
            try:
                retried=translate([simpler_headline_input(tasks[index]['title'],tasks[index].get('sourceExcerpt') or '') for index in retry])
                if len(retried)!=len(retry):raise ValueError('Headline retry count mismatch')
                retry_complete=True
                for index,headline in zip(retry,retried):values[index][0]=headline
            except Exception as exc:
                # Keep first-pass summaries even if the headline retry fails.
                print(json.dumps({'headlineRetryUnavailable':type(exc).__name__,'count':len(retry)}),flush=True)
        for index,(item,(headline,summary)) in enumerate(zip(tasks,values)):
            item['translationMethod']='machine-translation'
            set_translation(item,headline,summary,fallback_checked=retry_complete and index in retry)
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
    eligible=[]
    for item in news:
        topic=category(item.get('title',''),item.get('sourceExcerpt') or item.get('_excerpt',''))
        if topic is None:continue
        eligible.append({**item,'category':topic})
    selected=group_coverage(eligible,usable_translation)
    return {'schemaVersion':1,'generatedAt':now.isoformat(),'rankings':rankings,'brief':brief,
            'recap':{'asOf':asof,'weekStart':start.isoformat(),'weekEnd':end.isoformat(),'weekComplete':complete,'timezone':'America/New_York','method':'sector-etf-unadjusted-close-price-return',
                     'indices':[quotes[s] for s,_,_ in INDICES],'sectors':[quotes[s] for s,_,_ in SECTORS]},
            'news':selected,'feeds':feeds,'newsPolicy':{'maxAgeDays':14,'breakingMaxAgeHours':2,'displayOrder':'latest-first','importanceBasis':'source-event-and-reviewed-context','eventDeduplication':EVENT_DEDUPLICATION_VERSION}}


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
                if item.get('_translate'):
                    set_translation(item,item.get('headlineKo'),item.get('summaryKo',''))
                    if item['translationStatus']=='unavailable':item['summaryError']=type(exc).__name__
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
