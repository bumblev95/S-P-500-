"""Translate one short source passage per public news item, offline on the runner.

Translation never supplies evidence to the impact classifier. The English
headline/excerpt remain available for checking. Cache entries bind to exact
source text; a changed article cannot inherit an old Korean summary.
"""
import argparse
from decimal import Decimal
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from build_forecasts import atomic_json
from build_company_news import complete_sentences, normalize

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'facebook/nllb-200-distilled-600M'
VERSION = 'company-news-ko-v5'

MARINE_WORK_CONTEXT = r'\b(?:Wood Group|North Sea|oil|gas|rigs?|marine|drilling|offshore wind|at sea)\b'
OUTSOURCING_CONTEXT = r'\b(?:outsourc\w*|software|call\s*cent(?:er|re)s?|overseas|IT services)\b'
INVESTMENT_CONTEXT = r'\b(?:markets?|stocks?|invest\w*|funds?|trading|hedge|portfolio)\b'

# Match whole source phrases, not standalone ambiguous words (minutes, quant,
# offshore). Literal English inputs help NLLB keep the news/financial sense.
# Korean alternatives include normal nominal headlines and common synonyms.
# Each rule holds a source phrase, literal input, Korean requirements, a known
# wrong sense, and optional positive/excluded contexts for ambiguous phrases.
HEADLINE_TERMS = (
    (r"\b(?:(?:FOMC|Federal Open Market Committee|Federal Reserve)(?:'s)?\s+"
     r"(?:(?:last|latest)\s+)?(?:meeting\s+)?minutes|minutes\s+(?:of|from)\s+"
     r"(?:the\s+)?(?:FOMC|Federal Open Market Committee|Federal Reserve)"
     r"(?:'s)?(?:\s+(?:(?:last|latest)\s+)?(?:policy\s+)?meeting)?)\b",
     'written records of the Federal Reserve monetary policy meeting',
     (r'의사\s*록|회의\s*록|회의(?:의|에\s*(?:대한|관한)|에서)?\s*(?:서면\s*)?(?:기록|내용|논의)',
      r'FOMC|연준|연방\s*준비|미국\s*중앙\s*은행'),
     r'(?:FOMC|연준|연방\s*준비\s*제도)\s*(?:의\s*)?(?:분기|분간)|기록적(?:인|으로)?\s*기록', None, None),
    (r'\b(?:quant|quantitative)\s+((?:hedge\s+)?funds?)\b',
     r'investment \1 using mathematical and statistical trading strategies',
     (r'퀀트|계량|정량|양적|수학|통계', r'펀드|기금|자금|투자'),
     r'양자\s*(?:펀드|자금|기금|투자)', None, None),
    (r'\boffshore\s+(workers?)\b', r'\1 at sea',
     (r'해상|해양|바다|연안', r'노동자|근로자|작업자|직원|인력|종사자|근무자'),
     r'오프셔널', MARINE_WORK_CONTEXT, OUTSOURCING_CONTEXT),
    (r'\bcontrarian\b', 'against prevailing market sentiment',
     (r'역발상|역추세|반대|반하|반해|맞서|거스르|거슬러|역행|(?:주류|시장|통념).{0,20}다른',),
     r'역동적', INVESTMENT_CONTEXT, None),
)


# These rules apply to each field's own English text. Supplemental article
# context can disambiguate a word, but cannot introduce a missing source term.
# Exclusions run BEFORE Korean requirements: labor strikes, analyst ratings,
# state governors, physical weights and company sales must keep their meanings.
FINANCIAL_CONTEXT = r'\b(?:stocks?|shares?|equities|markets?|invest\w*|funds?|ETF\w*|index|indices|portfolio|S&P)\b'
MILITARY_CONTEXT = r'\b(?:military|missiles?|attacks?|bomb\w*|war|warplanes?|refiner\w*|airstrikes?|air strikes?)\b'
LABOR_CONTEXT = r'\b(?:workers?|unions?|labor|labour|wages?|pay dispute|industrial action|lightning|thunder|baseball)\b'
CONTEXT_TERMS = (
    (r'\bearnings calls?\b', 'company financial results conference call',
     (r'실적.{0,12}(?:발표|설명|콘퍼런스|컨퍼런스)|어닝.{0,3}콜',), r'수익\s*통화', None, None),
    (r'\bSeries I bonds?\b', 'U.S. inflation-linked Series I savings bond',
     (r'시리즈\s*I|I[-\s]*본드|I[-\s]*저축\s*채권|물가.{0,8}연동.{0,8}(?:채권|저축)',),
     r'신종\s*1\s*부채', None, None),
    (r'\b(?:Treasury Department|Department of the Treasury)\b', 'United States Treasury Department',
     (r'재무부',), r'기획\s*재정부', r'\b(?:U\.S\.|United States|Series I)\b', None),
    (r'\btech-heavy\b', 'with a large share of technology stocks',
     (r'기술주|기술\s*업종',), r'기술력', r'\bNasdaq\b', None),
    (r'\bcomparable sales\b', 'sales at stores open for at least one year',
     (r'(?:동일|기존|비교).{0,8}(?:매장|점포).{0,8}매출|1년.{0,15}매출',),
     r'비교적.{0,8}(?:판매|매출)', None, None),

    (r'\bequal[- ]weight(?:ed|ing)?\b', 'investment allocation with the same portfolio share for each stock',
     (r'동일\s*(?:가중|비중)|균등\s*(?:가중|비중|배분)|같은\s*비중|동등한\s*비중',),
     r'(?:같은|동등한|동일한|균등한)\s*무게', FINANCIAL_CONTEXT,
     r'\b(?:rating|rated|upgrades?|downgrades?|overweight|underweight|bars?|boxes?|kilograms?|grams?|weighing)\b'),
    (r"['\"]real['\"]\s+price\b", 'actual price',
     (r'실제|실질|진짜|실물',), r'실적.{0,6}가격', r'\b(?:oil|crude)\b', None),
    (r'\bstock (?:price )?fixing\b', 'stock price manipulation',
     (r'주가|주식|시세', r'조작|조종'), r'주식\s*고정',
     r'\b(?:scandal|manipulation|fraud)\b', r'\b(?:inventory|machinery|clamps?|devices?)\b'),
    (r'\bphysical\s+(?:crude\s+)?oil\b', 'crude oil for physical delivery',
     (r'석유|원유',), r'물유', None, None),
    (r'\bsell[- ]?offs?\b', 'market price decline',
     (r'매도|매각|하락|급락|폭락|약세',), r'(?:주식|증시|시장)\s*(?:매출|판매)', FINANCIAL_CONTEXT,
     r'\b(?:inventory|clearance|warehouses?|retailers?|unsold|business units?)\b'),
    (r'\b(air|military|missile|drone|retaliatory) strike(s?)\b', r'\1 attack\2',
     (r'공격|공습|타격|폭격',), r'파업', None, LABOR_CONTEXT),
    (r'\bstrike(s?)(?=\s+(?:on|against|to resume)\b)', r'attack\1',
     (r'공격|공습|타격|폭격',), r'파업', MILITARY_CONTEXT, LABOR_CONTEXT),
    (r'\bstriking(?=\s+(?:(?:Russian|Ukrainian|Iranian|Israeli)\s+)?(?:energy sites|oil refineries|refineries|military targets)\b)', 'attacking',
     (r'공격|공습|타격|폭격',), r'파업', None, LABOR_CONTEXT),
    (r"\b((?:central bank|Bank of (?:France|England|Japan|Canada)|Reserve Bank of (?:Australia|India|New Zealand))(?:'s)?)\s+governor\b",
     r'\1 chief', (r'총재|은행장|수장',), None, None, None),
    (r"\bgovernor\s+of\s+(?:the\s+)?((?:central bank|Bank of (?:France|England|Japan|Canada)|Reserve Bank of (?:Australia|India|New Zealand)))\b",
     r'chief of the \1', (r'총재|은행장|수장',), None, None, None),
    (r"\bhead of ((?:the )?(?:country's |[A-Za-z]+(?:'s)? )?central bank)\b",
     r'chief of \1', (r'총재|은행장|수장',), None, None, None),
    (r'\brate signal\b', 'interest rate policy signal',
     (r'금리',), r'금전\s*신호', r'\b(?:Fed|Federal Reserve|central bank|Warsh)\b', None),
    (r'\bprivate equity-owned (companies|businesses)\b', r'\1 owned by private investment funds',
     (r'사모|비공개\s*투자|민간\s*투자\s*(?:펀드|기금)',), r'개인\s*주식회사', None, None),
    (r'\bprivate equity\b', 'private investment fund',
     (r'사모|비공개\s*투자|민간\s*투자\s*(?:펀드|기금)',), r'개인\s*주식회사|프라이빗\s*에피티', None, None),
    (r'\brelease\s+(diesel|oil|crude) stocks\b', r'release stored \1 reserves',
     (r'비축|재고|저장',), None, None, r'\b(?:shares?|equities|stock market|energy sector)\b'),
)


def normalized_source(source):
    return unicodedata.normalize('NFKC', source or '').replace('’', "'").replace('‘', "'").replace('–', '-').replace('‐', '-').replace('‑', '-')


def valid_context_terms(text, source, source_context=''):
    source = normalized_source(source)
    context = source+' '+normalized_source(source_context)
    for pattern, _, expected, wrong, positive, excluded in CONTEXT_TERMS:
        if not re.search(pattern, source, re.I) or not term_context_matches(context, positive, excluded):
            continue
        if wrong and re.search(wrong, text, re.I):
            # A field may mention both military and railway/other labor strikes.
            # Keep the military meaning requirement, but only reject all 파업
            # tokens when every source strike occurrence has a military match.
            ambiguous_strike = False
            if wrong == r'파업':
                military_spans = [m.span() for p, _, _, w, positive, excluded in CONTEXT_TERMS
                                  if w == r'파업' and term_context_matches(context, positive, excluded)
                                  for m in re.finditer(p, source, re.I)]
                ambiguous_strike = any(not any(start <= m.start() and end >= m.end() for start, end in military_spans)
                                       for m in re.finditer(r'\bstrik(?:e|es|ing)\b', source, re.I))
            if not ambiguous_strike: return False
        if not all(re.search(required, text, re.I) for required in expected): return False
    return True


def valid_financial_facts(text, source):
    """Conservative source-field checks for amount scale and earnings misses.

    These catch known failure classes, not arbitrary translation errors. Never
    borrow an amount or a direction from the other field of the article.
    """
    source = normalized_source(source)
    amounts = []
    for match in re.finditer(r'\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(billion|million|trillion|bn|mn)\b', source, re.I):
        scale = {'billion': 10**9, 'bn': 10**9, 'million': 10**6, 'mn': 10**6, 'trillion': 10**12}[match[2].lower()]
        amounts.append(Decimal(match[1].replace(',', '')) * scale)
    if amounts:
        translated = []
        for match in re.finditer(r'((?:\d+(?:,\d{3})*(?:\.\d+)?\s*[조억만천백십]*\s*)+)달러', text):
            total = group = Decimal(0)
            pending = None
            for token in re.findall(r'\d+(?:,\d{3})*(?:\.\d+)?|[조억만천백십]', match[1]):
                if token in ('조', '억', '만'):
                    total += (group + (pending or 0)) * {'조': 10**12, '억': 10**8, '만': 10**4}[token]
                    group = Decimal(0)
                    pending = None
                elif token in ('천', '백', '십'):
                    group += (pending if pending is not None else 1) * {'천': 1000, '백': 100, '십': 10}[token]
                    pending = None
                else:
                    pending = Decimal(token.replace(',', ''))
            translated.append(total + group + (pending or 0))
        if any(amount not in translated for amount in amounts):
            return False
    if re.search(r'\b(?:sales|revenue|earnings)\s+miss(?:es|ed)?\s+(?:\w+\s+){0,2}expectations\b', source, re.I):
        if not re.search(r'미달|밑돌|하회|못\s*미(?:치|쳤|친)', text):
            return False
    if re.search(r'\b(?:LA|Los Angeles) primary\b', source, re.I):
        if not re.search(r'예비\s*선거|경선', text):
            return False
    return True


def valid_korean_summary(text, source_text='', source_context=''):
    # Keep valid_korean as the generic language gate for existing callers.
    # Validate the summary against the passage actually translated, not against
    # every term in the headline. Do not silently publish detected bad text.
    return (valid_korean_headline(text)
            and valid_context_terms(text, source_text, source_context)
            and valid_financial_facts(text, source_text))


def source_hash(article):
    return hashlib.sha256((article['title']+'\n'+article.get('summary', '')).encode()).hexdigest()


def short_passage(article):
    """Use a complete lead sentence, or the headline if the excerpt is cut off.

    Stock-picking questions and comparisons retain their question/opinion in the
    headline instead of turning a historical number into a new company event.
    """
    title, excerpt = article['title'], article.get('summary', '').strip()
    reference = article.get('impact', {}).get('status') == 'unclear'
    if reference: return title
    # Choose a complete sentence that actually contains the selected event.
    # A vague lead such as "long history of dividends" cannot replace today's
    # reported shareholder-return amount in the headline.
    evidence = article.get('impact', {}).get('evidence', [])
    for sentence in complete_sentences(excerpt):
        if 40 <= len(sentence) <= 320 and any(normalize(e) in normalize(sentence) for e in evidence if len(e) >= 20):
            return sentence
    return title


def valid_korean(text):
    return isinstance(text, str) and 3 <= len(text) <= 600 and len(re.findall(r'[가-힣]', text)) >= 3 and '<unk>' not in text and not text.startswith('한국어 요약 번역을 완료하지')


def term_context_matches(source, context, excluded):
    return ((context is None or re.search(context, source, re.I))
            and (excluded is None or not re.search(excluded, source, re.I)))


def valid_headline_terms(text, source_title):
    """Check only known source-bound senses; this is not general fact checking.

    Use the exact source title, never the excerpt: a title need not repeat every
    term in its lead summary. Unrelated quantum/offshore/time news stay valid.
    """
    source = unicodedata.normalize('NFKC', source_title).replace('’', "'").replace('‘', "'")
    for pattern, _, expected, wrong, context, excluded in HEADLINE_TERMS:
        if not re.search(pattern, source, re.I): continue
        if re.search(wrong, text, re.I): return False
        # With no marine evidence, offshore can also mean overseas outsourcing.
        # Do not demand a sea-based sense from an ambiguous source title.
        if not term_context_matches(source, context, excluded): continue
        if not all(re.search(required, text, re.I) for required in expected): return False
    return True


def valid_korean_headline(text, source_title='', source_context=''):
    """Reject obvious unfinished headlines, while allowing normal noun phrases.

    Known news terms also retain their source-title meaning. This conservative
    check is not a general grammar/meaning validator.
    Keep the broader summary validator separate: a bad title must not discard a
    complete Korean lead, including an already cached/reviewed summary.
    """
    if not valid_korean(text): return False
    text = unicodedata.normalize('NFKC', text).strip()
    if re.search(r'(?:\.{3}|…)\s*[\"\'”’!?]*$', text): return False
    closing = {')': '(', ']': '[', '}': '{'}
    opened = []
    for char in text:
        if char in closing.values(): opened.append(char)
        elif char in closing:
            if not opened or opened.pop() != closing[char]: return False
    if opened: return False
    tail = text.rstrip(' \t\r\n.,!?\"\'”’)]}:;')
    # These adverbs need a following predicate. Bare 처음/최초 and 첫 + noun
    # remain valid nominal headlines; do not reject them as sentence fragments.
    if re.search(r'(?:처음으로|최초로|(?:예상|전망|기대|관측|예측|전년|전월|이전|현재)보다)$', tail): return False
    if re.search(r'(?:^|[\s\"\'“‘])(?:왜|어떻게|언제|어디서|어디로|무엇을|누가|얼마나|'
                 r'그리고|하지만|그러나|만약|때문에|대해|관해|위해|따라|동안|'
                 r'은|는|이|가|을|를|의|에|에게|에서|으로|로|와|과)$', tail):
        return False
    return (not re.search(r'[가-힣]+(?:지만|면서|으며|는데|다면|으면|므로|에도)$', tail)
            and valid_headline_terms(text, source_title)
            and valid_context_terms(text, source_title, source_context)
            and valid_financial_facts(text, source_title))


def simpler_headline_input(title, source_excerpt=''):
    """Retry a complete lead clause without a trailing teaser/attribution.

    Only simplify the translation input; exact source text and its hash remain
    unchanged. The sentence splitter protects U.S./company abbreviations.
    """
    text = translation_input(title, source_excerpt)
    # Preserve an event's trailing milestone clause before taking a lead sentence.
    # Flattening "- a first for ..." to a comma can leave a dangling Korean adverb.
    first = re.search(r'\s*(?: - |[:;])\s*a first for\s+(.+)$', text, re.I)
    if first: text = text[:first.start()].strip()
    lead = next(complete_sentences(text), text)
    lead = re.sub(r'\bStocks are hitting records\b', 'Stock prices are at record highs', lead, flags=re.I)
    # A retained source lead can disambiguate bare "yields" without inventing
    # bond context for agricultural yields or changing the source/hash itself.
    if re.search(r'\b(?:Treasur(?:y|ies)|bond yields?|government bonds?)\b', title+' '+source_excerpt, re.I):
        lead = re.sub(r'\b(?:surging|soaring) yields\b', 'sharply rising bond interest rates', lead, flags=re.I)
    lead = re.sub(r'\s*(?: - |[:;])\s*', ', ', lead).strip()
    if first:
        # Make a planned execution explicit rather than a headline infinitive.
        planned = re.search(r'^(.+?) to be executed by firing squad\b', lead, re.I)
        if planned:
            lead = re.sub(r'\bshooter\b', 'gunman', lead, flags=re.I)
            lead = re.sub(r'\bto be executed\b', 'will be executed', lead, count=1, flags=re.I)
        copula = 'will be' if planned else 'is'
        return lead.rstrip(' .')+'. This '+copula+' the first such event for '+first.group(1).rstrip(' .')+'.'
    return lead


def translation_input(text, source_context=''):
    text = source = normalized_source(text)
    for pattern, replacement, _, _, context, excluded in CONTEXT_TERMS:
        if term_context_matches(source+' '+normalized_source(source_context), context, excluded):
            text = re.sub(pattern, replacement, text, flags=re.I)
    text = unicodedata.normalize('NFKC', text).replace('’', "'").replace('‘', "'").replace('—', ' - ').replace('–', '-').replace('‐', '-').replace('‑', '-')
    for pattern, replacement, _, _, context, excluded in HEADLINE_TERMS:
        if term_context_matches(text, context, excluded):
            text = re.sub(pattern, replacement, text, flags=re.I)
    # Expand compact financial-news jargon before NLLB sees it. Literal wording
    # prevents common false senses such as Treasury=finance ministry or yield=profit.
    replacements = [
        (r'\bTreasury yields\b', 'interest rates on U.S. government bonds'),
        (r'\bFed rate hike bets\b', 'expectations for a Federal Reserve interest rate increase'),
        (r'\bpare back\b', 'reduce'),
        (r'\bsharp selloff\b', 'sharp market decline'),
        (r'\bjobs report\b', 'employment report'),
        (r'\bsoft labor market\b', 'weak labor market'),
        (r'\bfed funds rate\b', 'Federal Reserve policy interest rate'),
        (r'\bcore inflation\b', 'underlying inflation'),
        (r'\bPCE data\b', 'personal consumption expenditures inflation data'),
        (r'\bmodest rate moves\b', 'small changes in interest rates'),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r'\bWall Street is looking for job growth of ([0-9,]+)', r'Economists expect U.S. employers to add \1 jobs', text, flags=re.I)
    text = re.sub(r'\bFed\b', 'Federal Reserve', text, flags=re.I)
    # Expand a headline noun phrase; "beat" otherwise becomes a physical blow.
    return re.sub(r'\bearnings beat\b(?=\s*(?:[:,.!?]|(?:and|but|puts?|fuels?)\b|$))', 'better-than-expected earnings', text, flags=re.I)


def engine(model_dir):
    import ctranslate2
    import tempfile
    import shutil
    from transformers import AutoTokenizer
    from ctranslate2.converters import TransformersConverter
    model_dir = Path(model_dir)/'nllb-600m'
    if not (model_dir/'model.bin').exists():
        model_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=model_dir.parent) as temporary:
            converted = Path(temporary)/'converted'
            TransformersConverter(MODEL).convert(str(converted), quantization='int8')
            tokenizer = AutoTokenizer.from_pretrained(MODEL, src_lang='eng_Latn', trust_remote_code=False)
            tokenizer.save_pretrained(str(converted/'tokenizer'))
            atomic_json(converted/'source.json', {'model': MODEL, 'license': 'CC-BY-NC-4.0'})
            shutil.move(str(converted), str(model_dir))
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir/'tokenizer'), src_lang='eng_Latn', local_files_only=True)
    translator = ctranslate2.Translator(str(model_dir), device='cpu', compute_type='int8', inter_threads=1, intra_threads=2)
    def translate(texts):
        texts = [translation_input(t) for t in texts]
        tokens = [tokenizer.convert_ids_to_tokens(tokenizer.encode(t, truncation=True, max_length=256)) for t in texts]
        rows = translator.translate_batch(tokens, target_prefix=[['kor_Hang'] for _ in tokens], beam_size=4, max_batch_size=24, max_decoding_length=160, repetition_penalty=1.1)
        return [tokenizer.decode(tokenizer.convert_tokens_to_ids(r.hypotheses[0][1:]), skip_special_tokens=True).strip() for r in rows]
    return translate


def verify_engine(translate):
    samples = ['Apple recalled 20 defective iPhones.', 'Revenue rose 6%.', 'Nvidia raises revenue outlook.']
    outputs = translate(samples)
    if len(outputs) != 3 or not all(valid_korean(t) for t in outputs) or '20' not in outputs[0] or not re.search('리콜|회수|제품 철수', outputs[0]) or '6' not in outputs[1] or not re.search('매출|수익|수입', outputs[1]) or not re.search('전망|예상', outputs[2]):
        raise ValueError('Translation smoke check failed: '+json.dumps(outputs, ensure_ascii=False))
    print(json.dumps({'translationSmokeCheck': outputs}, ensure_ascii=False), flush=True)


def translate_snapshot(root=ROOT, translate=None, model_dir=None):
    path = root/'news/latest.json'
    snapshot = json.loads(path.read_text())
    articles = [a for issuer in snapshot['issuers'].values() for a in issuer['articles']]
    reviewed_path = root/'news/korean-reviewed.json'
    reviewed = json.loads(reviewed_path.read_text()) if reviewed_path.exists() else {}
    cache_path = root/'research/source-cache/news-ko/translations.json'
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    tasks = {}
    for article in articles:
        passage = short_passage(article)
        key = hashlib.sha256((VERSION+'\n'+passage).encode()).hexdigest()
        ko = article.get('ko', {})
        review = reviewed.get(article['id'], {})
        if review.get('sourceHash') == source_hash(article) and valid_korean_summary(review.get('summary'), passage):
            cache[key] = review['summary']
        if ko.get('sourceHash') == source_hash(article) and ko.get('sourceText') == passage and ko.get('version') == VERSION and valid_korean_summary(ko.get('summary'), passage):
            if not valid_korean_summary(cache.get(key), passage): cache[key] = ko['summary']
        if not valid_korean_summary(cache.get(key), passage): tasks[key] = passage
    if tasks:
        if translate is None:
            translate = engine(model_dir or root/'research/source-cache/news-ko/model')
            verify_engine(translate)
        ordered = list(tasks)
        for start in range(0, len(ordered), 24):
            keys = ordered[start:start+24]
            values = translate([tasks[k] for k in keys])
            if len(values) != len(keys): raise ValueError('Translation count mismatch')
            for key, value in zip(keys, values):
                if not valid_korean_summary(value, tasks[key]):
                    print(json.dumps({'translationUnavailable': key, 'source': tasks[key][:120], 'output': value[:120]}, ensure_ascii=False), flush=True)
                    value = '한국어 요약 번역을 완료하지 못했습니다. 원문에서 내용을 확인해 주세요.'
                cache[key] = value
            atomic_json(cache_path, cache)
            print(json.dumps({'translatedPassages': min(start+24, len(ordered)), 'total': len(ordered)}), flush=True)
    for article in articles:
        passage = short_passage(article)
        key = hashlib.sha256((VERSION+'\n'+passage).encode()).hexdigest()
        review = reviewed.get(article['id'], {})
        checked = review.get('sourceHash') == source_hash(article) and cache[key] == review.get('summary')
        article['ko'] = {'version': VERSION, 'language': 'ko', 'summary': cache[key], 'sourceHash': source_hash(article),
                         'sourceTitle': article['title'], 'sourceExcerpt': article.get('summary', ''),
                         'sourceText': passage, 'status': 'unavailable' if cache[key].startswith('한국어 요약 번역을 완료') else 'ready',
                         'method': 'reviewed-summary' if checked else 'machine-translation', 'model': MODEL}
    snapshot['translation'] = {'version': VERSION, 'language': 'ko', 'articleCount': len(articles),
                                'completedAt': datetime.now(timezone.utc).isoformat(), 'model': MODEL}
    atomic_json(path, snapshot)
    return snapshot


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--reclassify', action='store_true')
    args = parser.parse_args()
    if args.reclassify:
        from build_company_news import reclassify_snapshot
        reclassify_snapshot()
    translate_snapshot(model_dir=args.model_dir)
