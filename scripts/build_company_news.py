"""Company-specific current news and explainable preliminary impact labels.

Display-only RSS metadata, never training, stock scores or trading decisions.
Labels describe reported company developments, not a predicted price move.
"""
import argparse
import hashlib
import json
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from threading import Event, Lock
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from build_forecasts import atomic_json
from research_universe import load_universe

ROOT = Path(__file__).resolve().parents[1]
PARSER = 'company-news-v1'
CLASSIFIER = 'company-impact-source-v2'
WINDOW_DAYS = 30
MAX_ARTICLES = 12
LABELS = {'positive': '호재', 'negative': '악재', 'mixed': '혼재',
          'neutral': '중립', 'unclear': '판단 유보'}
# Event phrases, rather than sentiment adjectives such as "great" / "bad".
RULES = [
    ('positive', '분석가 기대', r'\bwall street\b.{0,25}\b(?:sees?|expects?)\b.{0,30}\bupside\b|\banalysts?\b.{0,25}\b(?:bullish|optimistic)\b', '분석가가 추가 상승 여력에 긍정적인 의견을 제시했습니다. 회사의 확정 실적 변화가 아니며 목표주가 도달을 보장하지 않습니다.'),
    ('positive', '사업 확장', r'\b(?:entered the smart home|opens? (?:a |its )?new (?:plant|factory|facility|store)|expands? (?:its )?(?:production|capacity))\b', '새로운 사업·생산 영역으로 확장하는 내용입니다. 향후 판매 기회에 유리할 수 있지만 투자 비용과 수익성도 함께 보세요.'),
    ('positive', '판매·인도 실적 개선', r'\b(?:deliveries|vehicle sales)\b.{0,50}\b(?:clear the street|topped|above analyst estimates|above estimates|surpass(?:ed|ing)? expectations)\b|\bdeliver(?:ed|s)\b.{0,75}\b(?:beating|beat|surpassing)\b.{0,25}\bestimates\b|\bbeat\b.{0,30}\bdeliveries\b|\bbetter.than.expected\b.{0,20}\bdeliveries\b', '판매·인도량이 시장 예상을 웃돌았습니다. 수요에 유리한 소식이며, 실제 이익은 판매 가격과 비용도 확인해야 합니다.'),
    ('positive', '매출·이익 증가', r'\b(?:revenue|profit|income|earnings|eps|sales)\b.{0,35}\b(?:rose|grew|increased|growth|ahead of expectations)\b|\b(?:posts?|reports?)\b.{0,25}\b\d+(?:\.\d+)?%\b.{0,20}\b(?:revenue|profit|income)\b.{0,15}\bgrowth\b', '매출·이익 증가가 보도됐습니다. 사업 성과에 유리하지만 시장 예상보다 좋았는지도 함께 보세요.'),
    ('positive', '계약·수주', r'\b(?:receives?|received|awarded)\b.{0,65}\b(?:contract|award|order)\b|\bcontract modification\b.{0,50}\b(?:lifts?|increases?)\b', '신규 계약·수주가 향후 매출 확보에 도움이 될 수 있습니다. 매출 인식 시점과 수익성은 별도 확인이 필요합니다.'),
    ('positive', '제품 출시', r'\b(?:unveils?|launched|introduces?|launches?)\b.{0,50}\b(?:gemini|argon|roadster|novus|new)\b', '신제품·서비스 출시로 사업 기회가 넓어질 수 있습니다. 출시 자체가 판매 성공을 뜻하지는 않습니다.'),
    ('positive', '사업 제휴', r'\b(?:partners? with|partnering with|teamed up with|teams? up with|collaborates? with)\b', '다른 기업과의 사업 제휴는 고객·판매 기회를 넓힐 수 있습니다. 실제 매출과 이익 효과는 아직 확인이 필요합니다.'),
    ('negative', '노사·운영 부담', r'\b(?:workers?|employees?|union)\b.{0,45}\b(?:strike|strikes|walkout)\b|\b(?:workers?|employees?) strike\b', '파업·운영 차질은 비용과 서비스 제공에 부담이 될 수 있습니다. 영향 규모와 해결 여부를 함께 확인하세요.'),
    ('negative', '성장·판매 부담', r'\b(?:sales|revenue|earnings|profit|income)\b.{0,25}\b(?:declining|down from|dropped|declined)\b|\b(?:steep|sharp) profit drop\b|\b(?:revenue|sales)\b.{0,50}\b(?:much slower|more slowly)\b', '매출·이익 감소나 성장 둔화가 보도됐습니다. 일시적인 요인인지도 함께 확인해야 합니다.'),
    ('neutral', '경영진 변경', r'\b(?:names?|named|appoints?|appointed|announces?|promotes?)\b.{0,90}\b(?:ceo|cfo|chief executive|chief financial|retirement)\b|\b(?:retires?|retirement|succeeding)\b.{0,65}\b(?:ceo|cfo|chief executive|chief financial)\b', '경영진 교체·은퇴 소식입니다. 교체만으로 실적이 좋아지거나 나빠진다고 판단할 근거는 없습니다.'),
    ('neutral', '발표·행사 안내', r'\b(?:schedules?|announces?)\b.{0,55}\b(?:conference call|webcast|earnings release)\b|\b(?:to webcast|will host)\b.{0,35}\b(?:earnings|conference call)\b', '실적 발표·설명회 일정 안내입니다. 실적 결과가 아직 발표된 것은 아닙니다.'),
    ('neutral', '정기 배당', r'\bquarterly dividend\b.{0,20}\bdeclared\b', '정기 배당 공지입니다. 배당의 증가·감소가 확인되지 않아 영향은 중립으로 표시합니다.'),
    ('neutral', '전망 유지', r'\b(?:reaffirms?|maintains?|holds?)\b.{0,25}\b(?:guidance|outlook|forecast|targets)\b', '기존 사업 전망을 유지했다는 내용입니다. 상향·하향이 확인되지 않아 중립으로 표시합니다.'),
    ('positive', '매출·이익 증가', r'\b(?:revenue|profit|earnings|sales)\b.{0,30}\b(?:rises?|rose|jumps?|surges?|grew|grows?|increases?|increased|\d+(?:\.\d+)?% higher)\b', '매출·이익 증가를 보도해 사업 성과에 유리한 내용입니다. 예상 대비 수준은 별도 확인이 필요합니다.'),
    ('positive', '제품 출시', r'\b(?:introduces?|launches?|unveils?)\b.{0,80}\b(?:product|system|platform|module|chip|service|model|software|engine|device|kiosk|app)\b', '신제품·서비스 출시는 사업 기회를 넓힐 수 있습니다. 판매 성과와 수익성은 아직 별도 확인이 필요합니다.'),
    ('positive', '임상·허가 진전', r'\bpositive\b.{0,35}\b(?:trial|phase [123][ab]?|study)\b.{0,40}\b(?:results?|data)\b|\b(?:trial|study)\b.{0,35}\bmeets?\b.{0,25}\b(?:endpoint|goal)\b|\b(?:receives?|wins?)\b.{0,30}\bexpanded indication\b', '긍정적인 임상 결과·허가 범위 확대는 사업 진행에 유리할 수 있습니다. 후속 시험·판매 성과는 별도 확인이 필요합니다.'),
    ('positive', '실적 개선', r'\b(?:beats?|tops?|exceeds?)\b.{0,35}\b(?:earnings|revenue|profit|estimates|expectations)\b|\b(?:earnings|revenue|profit)\b.{0,25}\b(?:beat|above expectations)\b', '시장 예상보다 좋은 실적을 보도해 수익 기대에 유리합니다.'),
    ('positive', '판매·인도 실적 개선', r'\b(?:deliveries|vehicle sales|same.store sales)\b.{0,30}\b(?:beat|beats|exceed|exceeds|above expectations)\b|\bdelivery beat\b', '판매·인도 실적이 예상을 웃돌았다는 보도입니다. 이익과 마진은 별도 확인이 필요합니다.'),
    ('positive', '전망 상향', r'\b(?:raises?|raised|boosts?|boosted|lifts?|lifted)\b.{0,35}\b(?:guidance|outlook|forecast)\b', '회사의 실적 전망 상향은 향후 수익 기대에 유리합니다.'),
    ('positive', '주주 환원', r'\b(?:announces?|authorizes?|approves?|expands?|increases?|unveils?|launches?|new|record)\b.{0,65}\b(?:buyback|share repurchase|stock repurchase)\b|\b(?:raises?|increases?|hikes?)\b.{0,25}\bdividend\b|\breturn(?:ed|s)?\b.{0,45}\b(?:to shareholders|to investors)\b', '자사주 매입·배당 등 주주 환원은 주주 가치에 유리할 수 있습니다. 이전 기간 대비 증감은 별도 확인이 필요합니다.'),
    ('positive', '계약·수주', r'\b(?:wins?|won|secures?|secured|lands?|awarded)\b.{0,45}\b(?:contract|deal|order)\b|\b(?:signs?|signed)\b.{0,30}\b(?:supply agreement|contract)\b', '신규 계약·수주는 매출 확보에 유리할 수 있습니다. 규모와 수익성은 원문 확인이 필요합니다.'),
    ('positive', '승인·허가', r'\b(?:wins?|receives?|gets?|secures?|granted)\b.{0,30}\b(?:fda|regulatory)\b.{0,20}\b(?:approval|clearance)\b|\bfda\b.{0,20}\bapproves?\b', '제품의 규제 승인은 판매 기회 확대에 유리할 수 있습니다.'),
    ('positive', '분석가 상향', r'\b(?:upgrade[sd]?|upgrades|price target (?:raised|increased))\b', '분석가의 평가 상향입니다. 회사의 확정 실적 변화와는 구분해서 보세요.'),
    ('negative', '실적 부진', r'\b(?:misses?|missed)\b.{0,35}\b(?:earnings|revenue|profit|estimates|expectations)\b|\b(?:earnings|revenue|profit)\b.{0,30}\b(?:miss|below expectations|falls?|fell|declines?|drops?|slumps?)\b', '예상에 못 미친 실적·수익 감소는 수익 기대에 불리할 수 있습니다.'),
    ('negative', '전망 하향', r'\b(?:cuts?|cut|lowers?|lowered|slashed|slashes|reduces?|reduced|withdraws?)\b.{0,35}\b(?:guidance|outlook|forecast)\b|\bprofit warning\b', '회사의 실적 전망 하향·철회는 향후 수익 기대에 불리합니다.'),
    ('negative', '배당·환원 축소', r'\b(?:cuts?|cut|suspends?|suspended|reduces?|reduced|halts?|halted)\b.{0,25}\b(?:dividend|buyback|share repurchase)\b', '배당·자사주 매입 축소는 주주 환원 기대에 불리할 수 있습니다.'),
    ('negative', '소송·조사', r'\b(?:sued|lawsuit|lawsuits|faces? (?:a |an )?(?:probe|investigation)|under investigation|antitrust probe|antitrust investigation|fined|fines|penalty)\b', '소송·조사·제재 관련 비용과 사업 불확실성이 부담이 될 수 있습니다. 보도만으로 위법 확정은 아닙니다.'),
    ('negative', '제품·보안 사고', r'\b(?:recalls?|data breach|cyberattack|ransomware)\b', '제품 회수·보안 사고는 비용과 신뢰에 부담이 될 수 있습니다.'),
    ('negative', '수요·제품 부담', r'\b(?:weak|weaker|soft|softer|slowing|sluggish|falling)\b.{0,35}\bdemand\b|\b(?:service.loss bug|must replace phones|product defect|supply disruption)\b', '수요 둔화·제품 문제는 판매와 추가 비용에 부담이 될 수 있습니다.'),
    ('negative', '수익성 부담', r'\b(?:margin pressure|margin compression|contracting margins|profitability pressure)\b', '비용·마진 압박은 매출이 늘어도 수익성에 부담이 될 수 있습니다.'),
    ('negative', '성장·판매 부담', r'\b(?:slow|slower|slowing|weak|soft)\b.{0,20}\b(?:growth|sales)\b|\bgrowth problem\b|\b(?:sales|deliveries)\b.{0,25}\b(?:fell|fall|falls|decline|declines|drop|drops)\b', '성장 둔화·판매 부진은 사업 기대에 부담이 될 수 있습니다.'),
    ('negative', '임상·허가 차질', r'\bfda\b.{0,20}\brejects?\b|\bapproval (?:denied|rejected)\b|\b(?:trial|study)\b.{0,30}\b(?:fails?|misses?)\b.{0,25}\b(?:endpoint|goal)\b', '임상·허가 차질은 제품 개발과 판매 일정에 부담이 될 수 있습니다.'),
    ('negative', '재무·사업 위험', r'\b(?:bankruptcy|defaults? on|going concern|accounting fraud|delisting|export ban|export restrictions|contract (?:terminated|canceled|cancelled))\b', '재무·사업 지속 또는 판매 제한과 관련된 위험입니다.'),
    ('negative', '분석가 하향', r'\b(?:downgrade[sd]?|downgrades|price target (?:cut|lowered))\b', '분석가의 평가 하향입니다. 회사의 확정 실적 변화와는 구분해서 보세요.'),
    ('neutral', '발표·행사 안내', r'\b(?:to (?:report|announce) (?:its )?(?:quarter|earnings|results)|announces? (?:date|earnings date)|earnings call scheduled|to present at|participate[sd]? in.{0,35}conference)\b', '발표일·행사 안내이며 결과나 사업 조건의 변화는 아직 확인되지 않았습니다.'),
    ('neutral', '정기 배당', r'\b(?:declares?|announces?)\b.{0,20}\b(?:quarterly|regular)\b.{0,15}\bdividend\b', '정기 배당 공지입니다. 배당 증가·감소가 확인되지 않아 방향 판단은 중립입니다.'),
]
ALIASES = {
    'NVDA': ['Nvidia'], 'MSFT': ['Microsoft'], 'AAPL': ['Apple', 'iPhone'],
    'GOOG': ['Google', 'Alphabet'], 'GOOGL': ['Google', 'Alphabet'],
    'META': ['Meta Platforms', 'Meta'], 'AMZN': ['Amazon'],
    'TSLA': ['Tesla'], 'XOM': ['Exxon', 'ExxonMobil'],
    'BRK-B': ['Berkshire Hathaway', 'Berkshire'], 'BRK-A': ['Berkshire Hathaway', 'Berkshire'],
    'JPM': ['JPMorgan', 'J.P. Morgan'], 'UNH': ['UnitedHealth', 'United Healthcare'],
    'AMD': ['Advanced Micro Devices', 'AMD'], 'INTC': ['Intel'],
    'ON': ['onsemi', 'ON Semiconductor'], 'C': ['Citigroup', 'Citi'],
    'T': ['AT&T'], 'V': ['Visa'], 'BF-B': ['Brown-Forman'],
    'F': ['Ford'], 'GM': ['General Motors', 'GM'],
    'PG': ['P&G', 'Procter and Gamble'], 'JNJ': ['J&J', 'Johnson and Johnson'],
}
ANALYST_FIRMS = ['Morgan Stanley', 'Goldman Sachs', 'Wells Fargo', 'JPMorgan',
                 'Barclays', 'Bank of America', 'Citigroup', 'Jefferies', 'UBS',
                 'HSBC', 'Royal Bank of Canada', 'RBC', 'Oppenheimer', "Moody's", 'S&P Global', 'Fitch']


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def stamp(value):
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}: self.hidden += 1
    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.hidden: self.hidden -= 1
    def handle_data(self, text):
        if not self.hidden: self.parts.append(text)


def text_only(value):
    parser = TextOnly()
    parser.feed(str(value or '')[:20000])
    return re.sub(r'\s+', ' ', unescape(' '.join(parser.parts))).strip()


def normalize(value):
    value = value.replace('’', "'").replace('‘', "'").replace('—', ' ').replace('–', ' ')
    s = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def aliases(tickers, name):
    clean = re.sub(r'\([^)]*\)', '', name)
    clean = re.sub(r'\b(?:Inc|Corporation|Corp|plc|Ltd|Limited|Company|Co|Holdings|Holding|Group)\.?\b', '', clean, flags=re.I).strip(' .,')
    values = [clean, name] + [a for t in tickers for a in ALIASES.get(t, [])]
    # Distinctive brand names commonly omit a corporate descriptor in headlines.
    words = normalize(clean).split()
    descriptors = {'technologies', 'technology', 'international', 'industries', 'laboratories',
                   'lifesciences', 'pharmaceuticals', 'therapeutics', 'solutions', 'electric'}
    generic = {'american', 'general', 'united', 'global', 'national', 'first', 'international'}
    if len(words) >= 2 and words[1] in descriptors and len(words[0]) >= 5 and words[0] not in generic:
        values.append(words[0])
    return sorted({normalize(v) for v in values if len(normalize(v)) >= 3})


def mentions(text, tickers, names):
    n = ' ' + normalize(text) + ' '
    if any(' '+a+' ' in n for a in names): return True
    # A reused ticker on another exchange or a similarly named listed vehicle
    # is not this issuer. These feeds contain both real collision examples.
    if 'SPG' in tickers and re.search(r'\b(?:Super Group|JSE:\s*SPG)\b', text, re.I): return False
    if 'ARES' in tickers and re.search(r'\b(?:Ares Capital|ARCC)\b', text, re.I): return False
    if re.search(r'\b(?:JSE|TSX|ASX|LSE|NSE|BSE|HKEX):', text): return False
    for t in tickers:
        # Short English-word tickers (A, ON, IT...) require explicit stock syntax.
        if re.search(r'\((?:NASDAQ: ?|NYSE: ?)?'+re.escape(t)+r'\)|\$(?:'+re.escape(t)+r')\b|\b(?:NYSE|NASDAQ):\s*'+re.escape(t)+r'\b', text): return True
        if len(t) >= 3 and t not in {'ALL', 'ARE', 'CAT', 'DAY', 'FOR', 'HAS', 'KEY', 'NOW', 'PAY'} and re.search(r'(?<![A-Za-z0-9])'+re.escape(t)+r'(?![A-Za-z0-9])', text): return True
    return False


def safe_url(value):
    try:
        u = urlsplit(value)
        host = u.hostname or ''
        if (u.scheme != 'https' or u.username or u.password or u.port or
                not re.fullmatch(r'(?:[a-z0-9][a-z0-9-]*\.)+[a-z]{2,63}', host) or
                host.endswith(('.localhost', '.local', '.internal', '.example', '.test'))): return None
        query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                 if not k.startswith(('utm_', '.tsrc')) and k not in {'guccounter', 'ref'}]
        return urlunsplit(('https', u.netloc, u.path or '/', urlencode(query), ''))
    except (ValueError, TypeError):
        return None


def complete_sentences(text):
    """Only complete supplied sentences; never use a cut-off RSS tail as proof."""
    text = re.sub(r"\b(?:Inc|Corp|Co|Ltd|Mr|Dr)\.(?=\s)", lambda m: m.group(0)[:-1], text)
    text = text.replace('U.S.', 'US').replace('U.K.', 'UK')
    ends = [m.end() for m in re.finditer(r'[.!?](?:["”])?(?=\s+[A-Z]|$)', text)]
    start = 0
    for end in ends:
        if end-start > 12: yield text[start:end].strip()
        start = end


def news_kind(title):
    if re.search(r'\b(?:upgrades?|upgraded|downgrades?|downgraded|price target|analyst.{0,20}(?:rating|rated))\b', title, re.I): return 'analyst'
    if re.search(r'\b(?:stock|shares?|market returns|all.time high|record high)\b', title, re.I): return 'market'
    if re.search(r'\?|\b(?:vs\.?|versus|better buy|should you|undervalued|overvalued|investment case|cramer|stocks to (?:buy|watch|consider)|buy now|perfect time to buy)\b', title, re.I): return 'opinion'
    return 'company'


@lru_cache(maxsize=1200)
def mention_pattern(pool):
    return re.compile(r'(?<![a-z0-9])(?:'+'|'.join(re.escape(name) for name in sorted(pool, key=len, reverse=True))+r')(?![a-z0-9])')


def classify(title, tickers, names, other_names=None, summary=''):
    """Use issuer-anchored event clauses in the headline and complete RSS leads.

    The translated display text is never input. Rival actions, speculation,
    price moves and buying opinions are not evidence of company improvement.
    """
    base = {'classifier': CLASSIFIER, 'basis': 'headline-and-excerpt', 'confidence': 'limited'}
    def result(status, reason, topics=None, evidence=None, kind=None):
        return dict(base, status=status, label=LABELS[status], reason=reason,
                    topics=topics or [], evidence=evidence or [], kind=kind or news_kind(title))
    if not mentions(title, tickers, names):
        return result('unclear', '기사에 해당 회사가 확인되지 않아 영향을 구분할 근거가 부족합니다.')
    if 'ADP' in tickers and re.search(r'\b(?:private payrolls|jobs report|employment report)\b', title, re.I):
        return result('neutral', 'ADP가 발표한 고용 통계입니다. ADP 회사의 매출·이익 변화와 구분해서 보세요.', ['경제 통계 발표'], kind='company')
    others = (set(other_names) if other_names is not None else {normalize(a) for t, aa in ALIASES.items() if t not in tickers for a in aa}) - set(names)
    firms = {normalize(f) for f in ANALYST_FIRMS}
    own_full = set(names) | {normalize(t) for t in tickers if len(t) >= 3 and t not in {'ALL', 'ARE', 'CAT', 'DAY', 'FOR', 'HAS', 'KEY', 'NOW', 'PAY'}}
    def positions(text, pool):
        n = ' '+normalize(text)+' '
        pool = tuple(sorted(name for name in pool if len(name) >= 3))
        return [(m.start(), m.end(), m.group(0)) for m in mention_pattern(pool).finditer(n)] if pool else []
    uncertainty = r"\b(?:rumou?rs?|might|could|reportedly|expected to|poised to|set to|potential|possible|proposed|discuss|discussing|considering|analysts? expect(?:s|ing)?|projected to|would|denies?|does not|did not|no longer|fails? to|dismissed|cleared|avoids?|exits? bankruptcy|wins? (?:a )?lawsuit)\b|\bmay\s+(?:(?:soon|still|also|already)\s+)?(?:be|have|raise|cut|miss|beat|win|face|lose|increase|decrease|launch|announce|report|benefit|hurt|suffer|recover|boost|reduce|see)\b"
    snippets = [(title, 'headline')] + [(s, 'excerpt') for s in complete_sentences(summary)]
    anchored = []
    for text, origin in snippets:
        # A factual lead can clarify an opinion headline, but a question itself
        # cannot turn an anticipated event into a completed one.
        if '?' in text or re.search(r'\b(?:vs\.?|versus)\b', text, re.I): continue
        # Commas/contrast words separate rival subjects; shared subject lists
        # (Tesla and Rivian beat ...) remain together.
        # A short two-company list shares the delivery event that follows it.
        text = re.sub(r'\b([A-Z][A-Za-z. ]{1,25}), ([A-Z][A-Za-z. ]{1,25})(?=\s+Deliveries\b)', r'\1 and \2', text)
        clauses = re.split(r'[,;:]\s+(?=[A-Za-z])|\s+[—–]\s+|\s+(?:while|whereas|but|yet)\s+(?=[A-Za-z])', text)
        prior_own = False
        for clause in clauses:
            own = positions(clause, own_full)
            rival = positions(clause, others)
            normalized = ' '+normalize(clause)+' '
            for tone, topic, pattern, reason in RULES:
                for match in re.finditer(pattern, clause, re.I):
                    before = ' '+normalize(clause[:match.start()])+' '
                    after = ' '+normalize(clause[match.end():])+' '
                    # Block uncertainty and negation only around this event.
                    window = clause[max(0, match.start()-45):min(len(clause), match.end()+45)]
                    if re.search(uncertainty, window, re.I): continue
                    if topic == '소송·조사' and re.search(r'\b(?:files?|filed|brings?|brought)\b.{0,40}\blawsuit\b', clause, re.I): continue
                    if topic == '배당·환원 축소' and re.search(r'\bdividend growth\b', clause, re.I): continue
                    if topic in {'전망 상향', '전망 하향'} and re.search(r'\banalysts?\b.{0,50}\b(?:raises?|cuts?|lowers?|boosts?)\b', clause, re.I): continue
                    if topic in {'전망 상향', '전망 하향'} and re.search(r'\banalysts?\b', text, re.I): continue
                    firm_subject = any(normalized.strip().startswith(f+' ') and f in names for f in firms)
                    if firm_subject and topic in {'전망 상향', '전망 하향'} and not re.search(r'\b(?:its|own|20\d\d|fiscal|annual|quarterly|revenue|profit|earnings)\b', match.group(0), re.I): continue
                    is_rating = topic.startswith('분석가')
                    if is_rating:
                        context = re.search(r'\b(?:analysts?|rating|rated|stock|shares?|price target|wall street|buy|sell|outperform|underperform|overweight|underweight)\b', text, re.I)
                        broker = any(' '+f+' ' in normalized for f in firms)
                        if not context and not broker: continue
                        if re.search(r'\b(?:engine|software|system|platform|product|technology|model|chip|hardware|cloud|data|ai|gpu)\s+upgrades?\b', clause, re.I): continue
                        # A ratings/brokerage company is the source, not the recipient.
                        if any(re.search(r'\b(?:from|by)\s+'+re.escape(a)+r'(?:\s|$)', normalized) for a in names): continue
                        if any(re.search(r'\b'+re.escape(f)+r'(?: ratings| investment institute)?(?: has| had| on [a-z]+)?\s+(?:upgrades?|downgrades?|upgraded|downgraded)\b', normalized) for f in firms if f in names): continue
                        if any(normalized.strip().startswith(f+' ') and f in names for f in firms) and not mentions(clause[match.end():], tickers, names): continue
                    prefix_own = positions(clause[:match.start()], own_full)
                    prefix_other = positions(clause[:match.start()], others - firms if is_rating else others)
                    subject = bool(prefix_own) and (not prefix_other or max(p[1] for p in prefix_own) >= max(p[1] for p in prefix_other))
                    if topic not in {'계약·수주', '제품 출시', '사업 제휴'} and mentions(match.group(0), tickers, names) and not positions(match.group(0), others-firms): subject = True
                    # Explicit coordinated subjects share one actual event.
                    if not subject and prefix_own and prefix_other:
                        last = max(prefix_own+prefix_other, key=lambda p:p[1])
                        first = max(prefix_own, key=lambda p:p[1])
                        subject = ' and ' in before[min(first[0], last[0]):max(first[1], last[1])]
                    # "downgrades Exxon" / "FDA approves Pfizer drug" state the recipient after the verb.
                    if is_rating or topic == '승인·허가':
                        subject = subject or mentions(clause[match.start():match.end()+60], tickers, names)
                    if not subject and prior_own and (not rival or is_rating and not positions(clause, others-firms)):
                        subject = bool(re.match(r'(?:(?:and|but|yet|then)\s+)?(?:cuts?|raises?|lowers?|misses?|beats?|tops?|reports?|unveils?|suspends?|withdraws?|faces?|loses?|its\b|the company\b|the tech giant\b|the automaker\b|inc\b)', clause, re.I))
                        if topic in {'성장·판매 부담', '수익성 부담'} and re.match(r'(?:(?:and|but|yet)\s+)?(?:its\s+)?(?:slow|slower|slowing|weak|soft|growth problem|margin pressure|margin compression)\b', clause, re.I): subject = True
                        if is_rating and any(normalize(clause).startswith(f+' ') for f in firms): subject = True
                        if is_rating and normalize(clause).startswith('wall street '): subject = True
                    if not subject and origin == 'excerpt' and not rival and len(snippets) > 1:
                        # A standalone ticker-led feed may use "the company" or
                        # omit its name in the supplied lead. Never inherit a
                        # rival's explicitly named action.
                        subject = bool(re.match(r'(?:the company|the tech giant|the automaker|instead.{0,10}the tech giant)\b', clause, re.I))
                    if topic in {'계약·수주', '제품 출시'} and not subject: continue
                    if not subject: continue
                    anchored.append((tone, topic, reason, clause.strip()[:350], origin))
            if own: prior_own = True
            elif rival: prior_own = False
    tones = {m[0] for m in anchored}
    if not tones:
        kind = news_kind(title)
        reason = '주가 움직임·투자 의견 기사입니다. 회사 실적이나 사업 조건의 변화가 확인되지 않아 호재·악재로 분류하지 않았습니다.' if kind in {'market', 'opinion', 'analyst'} else '제공된 제목·짧은 요약에서 회사에 유리하거나 불리한 변화를 확인할 근거가 부족합니다.'
        return result('unclear', reason, kind=kind)
    status = 'mixed' if {'positive', 'negative'} <= tones else 'negative' if 'negative' in tones else 'positive' if 'positive' in tones else 'neutral'
    chosen = [m for m in anchored if m[0] != 'neutral' or status == 'neutral']
    reasons = {m[1]: m[2] for m in reversed(chosen)}
    reason = ('좋은 소식과 부담 요인이 함께 있습니다. ' if status == 'mixed' else '') + ' '.join(reversed(list(reasons.values())))
    analyst_view = all(m[1].startswith('분석가') or any(normalize(m[3]).startswith(f+' ') for f in firms) for m in chosen)
    kind = 'analyst' if analyst_view else 'company'
    return result(status, reason, list(dict.fromkeys(m[1] for m in chosen)), list(dict.fromkeys(m[3] for m in chosen)), kind)


def reclassify_snapshot(root=ROOT):
    """Refresh interpretations without changing article/source collection clocks."""
    path = root/'news/latest.json'
    snapshot = read(path)
    all_names = {a for v in snapshot['issuers'].values() for a in aliases(v['tickers'], v['name'])}
    for issuer in snapshot['issuers'].values():
        names = aliases(issuer['tickers'], issuer['name'])
        issuer['articles'] = [a for a in issuer['articles'] if mentions(a['title'], issuer['tickers'], names)]
        for article in issuer['articles']:
            article['impact'] = classify(article['title'], issuer['tickers'], names, all_names-set(names), article.get('summary', ''))
    snapshot['classifierVersion'] = CLASSIFIER
    snapshot['collection']['articleCount'] = sum(len(v['articles']) for v in snapshot['issuers'].values())
    snapshot['collection']['issuersWithArticles'] = sum(bool(v['articles']) for v in snapshot['issuers'].values())
    snapshot['limitations'][1] = 'Impact uses issuer-anchored headline clauses and complete supplied RSS sentences, not the full article or a price forecast.'
    atomic_json(path, snapshot)
    return snapshot


def feed_url(ticker):
    return 'https://feeds.finance.yahoo.com/rss/2.0/headline?' + urlencode({'s': ticker, 'region': 'US', 'lang': 'en-US'})


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'PublicCompanyNews/1.0', 'Accept': 'application/rss+xml, application/xml'}), timeout=15) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000: raise ValueError('Oversized news feed')
    return raw.decode('utf-8-sig')


def parse_feed(raw, tickers, name, observed_at, now, other_names=None):
    if len(raw.encode()) > 1_000_000 or re.search(r'<!DOCTYPE|<!ENTITY', raw, re.I): raise ValueError('Unsafe news XML')
    seen = stamp(observed_at)
    if not seen or seen > now: raise ValueError('Invalid observation time')
    channel = ET.fromstring(raw).find('channel')
    if channel is None: raise ValueError('Missing RSS channel')
    names, rows, rejected = aliases(tickers, name), [], 0
    for item in channel.findall('item')[:100]:
        title, summary = text_only(item.findtext('title')), text_only(item.findtext('description'))
        url = safe_url(item.findtext('link'))
        try:
            published = parsedate_to_datetime(item.findtext('pubDate') or '')
            if not published.tzinfo: raise ValueError('Missing timezone')
            published = published.astimezone(timezone.utc)
        except (ValueError, TypeError, OverflowError): rejected += 1; continue
        if not title or len(title) > 600 or not url or not now-timedelta(days=WINDOW_DAYS) <= published <= seen:
            rejected += 1; continue
        # A selected issuer appearing only in a rival's excerpt is not enough
        # to occupy its company-news feed.
        if not mentions(title, tickers, names): rejected += 1; continue
        if re.search(r'/(?:personal-finance|personalfinance)/|\b(?:inherit|dying (?:father|parent)|tax.free step.up|estate planning)\b', url+' '+title, re.I):
            rejected += 1; continue
        host = urlsplit(url).hostname
        source = text_only(item.findtext('source')) or host
        rows.append(dict(id='news:'+hashlib.sha256(url.encode()).hexdigest()[:24],
                         title=title, summary=summary[:300], publishedAt=published.isoformat(),
                         observedAt=observed_at, source={'name': source[:100], 'url': url},
                         provider='Yahoo Finance RSS', relevance='title' if mentions(title, tickers, names) else 'summary',
                         impact=classify(title, tickers, names, other_names, summary[:300])))
    rows.sort(key=lambda x: (x['publishedAt'], x['id']), reverse=True)
    unique, urls = {}, set()
    for row in rows:
        key = normalize(row['title'])
        if key not in unique and row['source']['url'] not in urls:
            unique[key] = row; urls.add(row['source']['url'])
    return list(unique.values())[:MAX_ARTICLES], rejected


def collect(groups, clock, fetcher, state, interval, workers):
    """At most three in-flight requests; access denial stops unstarted work."""
    lock, stop = Lock(), Event()
    until = stamp(state.get('blockedUntil'))
    if until and until > clock(): stop.set()
    stats = {'requests': 0, 'failures': 0, 'state': dict(state)}
    def one(entry):
        cik, tickers = entry
        if stop.is_set(): return cik, {'status': 'backoff'}
        checked = clock().isoformat()
        with lock: stats['requests'] += 1
        try:
            raw = fetcher(feed_url(sorted(tickers)[0]))
            observed = clock().isoformat()
            with lock: stats['failures'] = 0
            result = {'raw': raw, 'observedAt': observed, 'checkedAt': checked, 'status': 'ready'}
        except Exception as exc:
            status = 'access_denied' if isinstance(exc, HTTPError) and exc.code in (401, 403, 429) else 'request_failed'
            result = {'status': status, 'checkedAt': checked}
            with lock:
                stats['failures'] += 1
                if not stop.is_set() and (status == 'access_denied' or stats['failures'] >= 3):
                    stop.set()
                    stats['state'] = {'blockedUntil': (clock()+timedelta(hours=24 if status == 'access_denied' else 1)).isoformat(), 'reason': status}
        finally:
            if interval: time.sleep(interval)
        return cik, result
    captures = {}
    with ThreadPoolExecutor(max_workers=max(1, min(3, workers))) as pool:
        for cik, result in pool.map(one, sorted(groups.items())):
            captures[cik] = result
            if len(captures) % 50 == 0:
                print(json.dumps({'processedIssuers': len(captures), 'requests': stats['requests']}), flush=True)
    return captures, stats['requests'], stats['state'] if stop.is_set() else {}, 'backoff' if stop.is_set() else None


def build(root=ROOT, download=True, now=None, fetcher=fetch, only=None, interval=.4, workers=1):
    clock = lambda: now or datetime.now(timezone.utc)
    started = clock()
    members = {s.upper().replace('.', '-'): m for s, m in load_universe(root)['members'].items()}
    groups = {}
    for ticker, member in members.items(): groups.setdefault(str(member['cik']), []).append(ticker)
    names_by_cik = {cik: aliases(tt, members[tt[0]]['name']) for cik, tt in groups.items()}
    all_names = {a for aa in names_by_cik.values() for a in aa}
    old, state = read(root/'news/latest.json'), read(root/'news/request-state.json')
    until = stamp(state.get('blockedUntil'))
    blocked = 'backoff' if download and until and until > started else None
    issuers, errors, attempts = {}, [], 0
    selected_groups = {cik: tt for cik, tt in groups.items() if only is None or bool(set(tt) & set(only))}
    captures = {}
    if download:
        captures, attempts, state, blocked = collect(selected_groups, clock, fetcher, state, interval, workers)
    for cik, tickers in sorted(groups.items()):
        current = clock()
        prior = old.get('issuers', {}).get(cik, {})
        if prior.get('cik') != int(cik): prior = {}
        articles = [e for e in prior.get('articles', []) if stamp(e.get('publishedAt')) and stamp(e.get('observedAt')) and
                    current-timedelta(days=WINDOW_DAYS) <= stamp(e['publishedAt']) <= stamp(e['observedAt']) <= current and
                    mentions(e.get('title', ''), tickers, names_by_cik[cik])]
        feed = dict(prior.get('feed', {}))
        cache_path = root/f'research/source-cache/news/CIK{int(cik):010d}.json'
        raw, observed, online = None, None, False
        other_names = all_names - set(names_by_cik[cik])
        selected = only is None or bool(set(tickers) & set(only))
        status = feed.get('status', 'not_collected')
        if selected and download:
            capture = captures[cik]
            status = capture['status']
            if capture.get('checkedAt'): feed['checkedAt'] = capture['checkedAt']
            if status == 'ready': raw, observed, online = capture['raw'], capture['observedAt'], True
            elif status != 'backoff': errors.append({'cik': cik, 'code': status})
        if selected and not download and cache_path.exists():
            cache = read(cache_path)
            if cache.get('sourceHash') == hashlib.sha256(cache.get('raw', '').encode()).hexdigest():
                raw, observed = cache['raw'], cache['observedAt']
            else: errors.append({'cik': cik, 'code': 'invalid_capture'})
        if raw is not None:
            try:
                articles, rejected = parse_feed(raw, tickers, members[tickers[0]]['name'], observed, clock(), other_names)
                status = 'ready' if online else 'captured'
                feed.update(lastSuccessAt=observed, rejectedRows=rejected, sourceHash=hashlib.sha256(raw.encode()).hexdigest())
                if online:
                    atomic_json(cache_path, {'raw': raw, 'observedAt': observed, 'sourceHash': feed['sourceHash']})
            except (ValueError, TypeError, KeyError, ET.ParseError):
                status = 'invalid_response'; errors.append({'cik': cik, 'code': status})
        # Retained articles preserve their source observation even if rules change.
        for article in articles: article['impact'] = classify(article['title'], tickers, names_by_cik[cik], other_names, article.get('summary', ''))
        feed.update(status=status, sourceUrl=feed_url(sorted(tickers)[0]))
        issuers[cik] = dict(cik=int(cik), name=members[tickers[0]]['name'], tickers=tickers, feed=feed, articles=articles)
    if download and not blocked: state = {}
    current = clock()
    fresh = [v for v in issuers.values() if v['feed'].get('status')=='ready' and stamp(v['feed'].get('lastSuccessAt')) and
             timedelta(0) <= current-stamp(v['feed']['lastSuccessAt']) <= timedelta(days=2)]
    payload = dict(schemaVersion=1, parserVersion=PARSER, classifierVersion=CLASSIFIER, generatedAt=current.isoformat(),
                   windowDays=WINDOW_DAYS, symbols={s: str(m['cik']) for s, m in members.items()}, issuers=issuers,
                   collection=dict(mode='online' if download else 'offline', requests=attempts, targetIssuers=len(groups),
                                   freshIssuers=len(fresh), issuersWithArticles=sum(bool(v['articles']) for v in issuers.values()),
                                   articleCount=sum(len(v['articles']) for v in issuers.values()), blockedReason=blocked, errors=errors),
                   limitations=['Company-related Yahoo RSS headlines and supplied short excerpts, not comprehensive news coverage.',
                                'Impact uses issuer-anchored headline clauses and complete supplied RSS sentences, not the full article or a price forecast.',
                                'Neutral is a matched informational event. Missing or ambiguous evidence is unclear, not neutral.',
                                'Display-only: labels are not model features, stock scores or buy/sell signals.'])
    atomic_json(root/'news/latest.json', payload)
    if download: atomic_json(root/'news/request-state.json', state)
    print(json.dumps(payload['collection'], ensure_ascii=False), flush=True)
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--reclassify', action='store_true', help='Reclassify the retained snapshot without any collection or clock changes')
    parser.add_argument('--symbols', help='Only refresh these comma-separated tickers; retain all other issuers')
    args = parser.parse_args()
    if args.reclassify: reclassify_snapshot()
    else: build(download=not args.offline, only=[s.strip().upper().replace('.', '-') for s in args.symbols.split(',')] if args.symbols else None, workers=3)
