"""Translate one short source passage per public news item, offline on the runner.

Translation never supplies evidence to the impact classifier. The English
headline/excerpt remain available for checking. Cache entries bind to exact
source text; a changed article cannot inherit an old Korean summary.
"""
import argparse
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


def valid_korean_headline(text):
    """Reject obvious unfinished headlines, while allowing normal noun phrases.

    This conservative surface check is not a general grammar/meaning validator.
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
    if re.search(r'(?:^|[\s\"\'“‘])(?:왜|어떻게|언제|어디서|어디로|무엇을|누가|얼마나|'
                 r'그리고|하지만|그러나|만약|때문에|대해|관해|위해|따라|동안|'
                 r'은|는|이|가|을|를|의|에|에게|에서|으로|로|와|과)$', tail):
        return False
    return not re.search(r'[가-힣]+(?:지만|면서|으며|는데|다면|으면|므로|에도)$', tail)


def simpler_headline_input(title):
    """Retry a complete lead clause without a trailing teaser/attribution.

    Only simplify the translation input; exact source text and its hash remain
    unchanged. The sentence splitter protects U.S./company abbreviations.
    """
    text = translation_input(title)
    lead = next(complete_sentences(text), text)
    return re.sub(r'\s*(?: - |[:;])\s*', ', ', lead).strip()


def translation_input(text):
    text = unicodedata.normalize('NFKC', text).replace('’', "'").replace('‘', "'").replace('—', ' - ').replace('–', '-')
    # Expand compact financial-news jargon before NLLB sees it. Literal wording
    # prevents common false senses such as Treasury=finance ministry or yield=profit.
    replacements = [
        (r'\bTreasury yields\b', 'interest rates on U.S. government bonds'),
        (r'\bFed rate hike bets\b', 'expectations for a Federal Reserve interest rate increase'),
        (r'\bpare back\b', 'reduce'),
        (r'\bsharp selloff\b', 'sharp market decline'),
        (r"\bFederal Reserve's last meeting minutes\b", "minutes from the Federal Reserve's latest policy meeting"),
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
        if review.get('sourceHash') == source_hash(article) and valid_korean(review.get('summary')):
            cache[key] = review['summary']
        if ko.get('sourceHash') == source_hash(article) and ko.get('sourceText') == passage and ko.get('version') == VERSION and valid_korean(ko.get('summary')):
            cache.setdefault(key, ko['summary'])
        if not valid_korean(cache.get(key)): tasks[key] = passage
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
                if not valid_korean(value):
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
