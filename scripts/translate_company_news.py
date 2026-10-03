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

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'Helsinki-NLP/opus-mt-tc-big-en-ko'
VERSION = 'company-news-ko-v1'


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
    # Protect decimals, corporate abbreviations and tickers from sentence cuts.
    for match in re.finditer(r'[.!?](?:["”])?(?=\s+[A-Z]|$)', excerpt):
        sentence = excerpt[:match.end()].strip()
        if len(sentence) >= 45 and not re.search(r'\b(?:Inc|Corp|Co|U\.S|Mr|Dr)\.$', sentence):
            return sentence if len(sentence) <= 320 else title
    return title


def valid_korean(text):
    return isinstance(text, str) and 3 <= len(text) <= 600 and len(re.findall(r'[가-힣]', text)) >= 3 and '<unk>' not in text


def engine(model_dir):
    import ctranslate2
    from transformers import MarianTokenizer
    model_dir = Path(model_dir)
    tokenizer_dir = model_dir/'tokenizer'
    if not (model_dir/'model.bin').exists():
        from ctranslate2.converters import TransformersConverter
        model_dir.parent.mkdir(parents=True, exist_ok=True)
        TransformersConverter(MODEL).convert(str(model_dir), quantization='int8')
        MarianTokenizer.from_pretrained(MODEL).save_pretrained(tokenizer_dir)
    tokenizer = MarianTokenizer.from_pretrained(tokenizer_dir, local_files_only=True)
    translator = ctranslate2.Translator(str(model_dir), device='cpu', compute_type='int8', inter_threads=1, intra_threads=2)
    def translate(texts):
        texts = [unicodedata.normalize('NFKC', t).replace('’', "'").replace('‘', "'").replace('—', ' - ').replace('–', '-') for t in texts]
        tokens = [tokenizer.convert_ids_to_tokens(tokenizer.encode(t, truncation=True, max_length=192)) for t in texts]
        rows = translator.translate_batch(tokens, beam_size=3, max_batch_size=24, max_decoding_length=160, repetition_penalty=1.1)
        return [tokenizer.decode(tokenizer.convert_tokens_to_ids(r.hypotheses[0]), skip_special_tokens=True).strip() for r in rows]
    return translate


def translate_snapshot(root=ROOT, translate=None, model_dir=None):
    path = root/'news/latest.json'
    snapshot = json.loads(path.read_text())
    articles = [a for issuer in snapshot['issuers'].values() for a in issuer['articles']]
    cache_path = root/'research/source-cache/news-ko/translations.json'
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    tasks = {}
    for article in articles:
        passage = short_passage(article)
        key = hashlib.sha256((VERSION+'\n'+passage).encode()).hexdigest()
        ko = article.get('ko', {})
        if ko.get('sourceHash') == source_hash(article) and ko.get('sourceText') == passage and ko.get('version') == VERSION and valid_korean(ko.get('summary')):
            cache.setdefault(key, ko['summary'])
        if not valid_korean(cache.get(key)): tasks[key] = passage
    if tasks:
        translate = translate or engine(model_dir or root/'research/source-cache/news-ko/model')
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
        article['ko'] = {'version': VERSION, 'language': 'ko', 'summary': cache[key], 'sourceHash': source_hash(article),
                         'sourceText': passage, 'status': 'unavailable' if cache[key].startswith('한국어 요약 번역을 완료') else 'ready',
                         'method': 'machine-translation', 'model': MODEL}
    snapshot['translation'] = {'version': VERSION, 'language': 'ko', 'articleCount': len(articles),
                                'completedAt': datetime.now(timezone.utc).isoformat(), 'model': MODEL}
    atomic_json(path, snapshot)
    return snapshot


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path)
    args = parser.parse_args()
    translate_snapshot(model_dir=args.model_dir)
