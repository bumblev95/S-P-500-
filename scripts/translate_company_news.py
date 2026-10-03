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
MODEL = 'Helsinki-NLP/opus-mt-tc-big-en-ko'
VERSION = 'company-news-ko-v3'


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
    return isinstance(text, str) and 3 <= len(text) <= 600 and len(re.findall(r'[가-힣]', text)) >= 3 and '<unk>' not in text


def separate_vocabularies(model_dir, tokenizer):
    """CTranslate2's Marian converter registers one vocabulary for both sides.

    This OPUS model uses separate English/Korean vocabularies with equal sizes.
    Retain the converted weight row order, but give each side its own token
    strings; otherwise even correctly decoded Korean produces unrelated text.
    """
    shared = model_dir/'shared_vocabulary.json'
    source_path = model_dir/'source_vocabulary.json'
    size = len(json.loads((shared if shared.exists() else source_path).read_text()))
    for side, encoder in [('source', tokenizer.encoder), ('target', tokenizer.target_encoder)]:
        ordered = {value: token for token, value in encoder.items()}
        if any(i not in ordered for i in range(size)): raise ValueError('Incomplete '+side+' vocabulary')
        atomic_json(model_dir/(side+'_vocabulary.json'), [ordered[i] for i in range(size)])
    if shared.exists(): shared.unlink()


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
    separate_vocabularies(model_dir, tokenizer)
    translator = ctranslate2.Translator(str(model_dir), device='cpu', compute_type='int8', inter_threads=1, intra_threads=2)
    def translate(texts):
        texts = [unicodedata.normalize('NFKC', t).replace('’', "'").replace('‘', "'").replace('—', ' - ').replace('–', '-') for t in texts]
        # convert_ids_to_tokens uses Marian's TARGET decoder even for English
        # source IDs when vocabularies are separate. Keep the SOURCE pieces.
        tokens = [tokenizer.tokenize(t)[:191]+[tokenizer.eos_token] for t in texts]
        rows = translator.translate_batch(tokens, beam_size=3, max_batch_size=24, max_decoding_length=160, repetition_penalty=1.1)
        # English/Korean Marian uses different source and target vocabularies.
        # Decode target SentencePiece strings directly; mapping through the
        # source token IDs corrupts names, numbers and the entire translation.
        return [tokenizer.spm_target.decode([t for t in r.hypotheses[0] if t not in tokenizer.all_special_tokens]).strip() for r in rows]
    return translate


def verify_engine(translate):
    samples = ['The company recalls 20 phones.', 'Revenue rose 6%.', 'Nvidia raises revenue outlook.']
    outputs = translate(samples)
    if len(outputs) != 3 or not all(valid_korean(t) for t in outputs) or '20' not in outputs[0] or '6' not in outputs[1] or '전망' not in outputs[2]:
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
