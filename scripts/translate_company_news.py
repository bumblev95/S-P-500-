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
VERSION = 'company-news-ko-v4'


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


def engine(model_dir):
    import ctranslate2
    import sentencepiece
    import tempfile
    import zipfile
    import shutil
    import yaml
    from urllib.request import urlopen
    model_dir = Path(model_dir)/'marian-2022'
    source_model = model_dir/'source.spm'
    target_model = model_dir/'target.spm'
    if not (model_dir/'model.bin').exists():
        from ctranslate2.converters import MarianConverter
        model_dir.parent.mkdir(parents=True, exist_ok=True)
        # Convert the original release with separate vocabularies/embeddings.
        url = 'https://object.pouta.csc.fi/Tatoeba-MT-models/eng-kor/opusTCv20210807-sepvoc_transformer-big_2022-07-28.zip'
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); archive = folder/'model.zip'
            with urlopen(url, timeout=60) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with zipfile.ZipFile(archive) as bundle:
                entries = {Path(n).name: n for n in bundle.namelist() if not n.endswith('/')}
                print(json.dumps({'originalModelFiles': sorted(entries)}, ensure_ascii=False), flush=True)
                selected = [name for name in entries if name.endswith(('.npz', '.spm', '.yml', '.vocab', '.sh')) or name == 'README.md']
                for name in selected:
                    (folder/name).write_bytes(bundle.read(entries[name]))
            for name in ['preprocess.sh', 'postprocess.sh', 'decoder.yml']:
                print(json.dumps({'originalConfig': name, 'content': (folder/name).read_text()[:2500]}, ensure_ascii=False), flush=True)
            weights = sorted(folder.glob('*.npz'))
            if not weights: raise ValueError('Original model weights missing')
            model_path = next((p for p in weights if p.name == 'model.npz'), weights[0])
            vocab_paths = None
            for config in folder.glob('*decoder.yml'):
                options = yaml.safe_load(config.read_text())
                if options.get('vocabs'):
                    vocab_paths = [folder/Path(n).name for n in options['vocabs']]
                    break
            if vocab_paths is None:
                source_vocabs, target_vocabs = list(folder.glob('*.src.vocab')), list(folder.glob('*.trg.vocab'))
                if len(source_vocabs) != 1 or len(target_vocabs) != 1:
                    raise ValueError('Original model source and target vocabularies missing')
                vocab_paths = [source_vocabs[0], target_vocabs[0]]
            if len(vocab_paths) != 2 or not all(p.exists() for p in vocab_paths):
                raise ValueError('Original model decoder vocabulary paths invalid')
            # Marian's .vocab format lists one token per line in model-index
            # order. CTranslate2's converter instead requires indexed YAML.
            converted_paths = []
            for index, vocab in enumerate(vocab_paths):
                raw = vocab.read_text()
                if vocab.suffix == '.vocab':
                    tokens = raw.splitlines()
                    if not tokens or any(not token for token in tokens) or len(set(tokens)) != len(tokens):
                        raise ValueError('Original model flat vocabulary invalid')
                    mapping = {token: position for position, token in enumerate(tokens)}
                elif raw.lstrip().startswith('{'):
                    mapping = json.loads(raw)
                else:
                    converted_paths.append(vocab)
                    continue
                if mapping is not None:
                    if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, int) for k, v in mapping.items()):
                        raise ValueError('Original model vocabulary mapping invalid')
                    converted = folder/f'vocabulary-{index}.yml'
                    converted.write_text('\n'.join(json.dumps(k, ensure_ascii=False)+': '+str(v) for k, v in mapping.items())+'\n')
                    converted_paths.append(converted)
            vocab_paths = converted_paths
            MarianConverter(str(model_path), [str(p) for p in vocab_paths]).convert(str(model_dir), quantization='int8')
            shutil.copyfile(folder/'source.spm', source_model)
            shutil.copyfile(folder/'target.spm', target_model)
            atomic_json(model_dir/'source.json', {'url': url, 'sha256': digest, 'license': 'CC-BY-4.0'})
    source = sentencepiece.SentencePieceProcessor(model_file=str(source_model))
    target = sentencepiece.SentencePieceProcessor(model_file=str(target_model))
    source_vocab = json.loads((model_dir/'source_vocabulary.json').read_text())
    probes = ['Revenue rose 6%.', 'revenue rose 6%.', 'The company recalls 20 phones.', 'the company recalls 20 phones.']
    print(json.dumps({'tokenizationProbe': [{'text': t, 'tokens': source.encode(t, out_type=str), 'missing': [p for p in source.encode(t, out_type=str) if p not in source_vocab]} for t in probes]}, ensure_ascii=False), flush=True)
    translator = ctranslate2.Translator(str(model_dir), device='cpu', compute_type='int8', inter_threads=1, intra_threads=2)
    def translate(texts):
        texts = [unicodedata.normalize('NFKC', t).replace('’', "'").replace('‘', "'").replace('—', ' - ').replace('–', '-') for t in texts]
        tokens = [source.encode(t, out_type=str)[:191] for t in texts]
        rows = translator.translate_batch(tokens, beam_size=3, max_batch_size=24, max_decoding_length=160, repetition_penalty=1.1)
        return [target.decode([t for t in r.hypotheses[0] if t not in {'<s>', '</s>', '<pad>'}]).strip() for r in rows]
    return translate


def verify_engine(translate):
    samples = ['The company recalls 20 phones.', 'Revenue rose 6%.', 'Nvidia raises revenue outlook.']
    outputs = translate(samples)
    print(json.dumps({'translationDiagnostics': translate(['revenue rose 6%.', 'the company recalls 20 phones.', 'The company reported a 6% increase in revenue.', 'The company will recall 20 defective phones.'])}, ensure_ascii=False), flush=True)
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
