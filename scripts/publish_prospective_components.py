"""Publish legacy 21-session components ONLY on the isolated research branch.

Live CLI has no backdate, model, weight, origin or symbol-selection switches.
Source bytes, normalized inputs and predictions are committed before the original
freezer reads HEAD. No target data, production publish function or ranking runs.
"""
from __future__ import annotations

import concurrent.futures
import csv
import gzip
import hashlib
import importlib.metadata
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from audit_prospective_blends import target_close_utc, verify_issue_artifact
from freeze_prospective_blends import freeze_one, parse_time, target_start_utc
from prospective_blends import (COHORT_COUNT, REGISTERED_PROTOCOL_SHA256,
                               is_xnys_session, target_date)

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'research/joint-indicator/prospective-publication-v1'
STUDY = 'research/joint-indicator/prospective-blend-v1'
STATE_BRANCH = 'research/prospective-21-issues'
SOURCE_LOCK_SHA256 = 'c89a31e37ec0b277f5a472a80db2fe4deb6fb027f606f9810b74bb5af9fc976d'
PROXIES = ('SPY', 'QQQ', 'HYG', 'IEF', 'UUP', '^VIX')
FIELDS = ('model', 'symbol', 'asOf', 'issuedAt', 'horizon', 'anchor',
          'bear', 'base', 'bull', 'direction', 'dailyDrift', 'volatility')


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(',', ':')) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def git_bytes(commit, path):
    return subprocess.check_output(['git', 'show', f'{commit}:{path}'], cwd=ROOT)


def latest_settled(now):
    day = now.date()
    for _ in range(10):
        origin = day.isoformat()
        if is_xnys_session(origin) and now >= target_close_utc(origin) + timedelta(minutes=15):
            return origin
        day -= timedelta(days=1)
    raise ValueError('No settled session in the fixed calendar')


def verify_sources(check_dependencies=True):
    path = ROOT / PREFIX / 'SOURCE-LOCK.json'
    raw = path.read_bytes()
    if digest(raw) != SOURCE_LOCK_SHA256:
        raise ValueError('Legacy source lock changed')
    lock = json.loads(raw)
    for name, evidence in lock['files'].items():
        source = ROOT / PREFIX / 'legacy' / name
        if digest(source.read_bytes()) != evidence['sha256']:
            raise ValueError(f'Legacy source changed: {name}')
        if git_bytes(lock['legacyCommit'], evidence['sourcePath']) != source.read_bytes():
            raise ValueError(f'Legacy source is not original Git bytes: {name}')
    if check_dependencies:
        for name, version in lock['requirements'].items():
            if importlib.metadata.version(name) != version:
                raise ValueError(f'Expected {name}=={version}')
    if digest((ROOT / STUDY / 'PROTOCOL.json').read_bytes()) != REGISTERED_PROTOCOL_SHA256:
        raise ValueError('The registered 21-session protocol changed')
    return lock


def assert_state_branch():
    if git('branch', '--show-current') != STATE_BRANCH:
        raise ValueError(f'Publication is restricted to {STATE_BRANCH}; never main or the PR branch')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Publication requires a clean tracked worktree and index')


def verify_activation(now):
    # Preserve the protocol's review-before-capture condition. The record names
    # the reviewed code and hashes; it does not claim a GitHub/human approval.
    activation = json.loads((ROOT / PREFIX / 'ACTIVATION.json').read_bytes())
    if (activation.get('protocolSha256') != REGISTERED_PROTOCOL_SHA256 or
            activation.get('sourceLockSha256') != SOURCE_LOCK_SHA256 or
            activation.get('enabled') is not True or
            parse_time(activation['reviewedAt']) > now):
        raise ValueError('No valid reviewed activation for this registered study')
    commit = activation['reviewedCodeCommit']
    if subprocess.run(['git', 'merge-base', '--is-ancestor', commit, 'HEAD'], cwd=ROOT,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise ValueError('Reviewed code commit is not an ancestor of publication')
    paths = ('scripts/publish_prospective_components.py',
             f'{PREFIX}/legacy/generate.py', 'scripts/freeze_prospective_blends.py',
             'scripts/audit_prospective_blends.py', 'scripts/prospective_blends.py')
    if set(activation['codeSha256']) != set(paths):
        raise ValueError('Incomplete reviewed code hashes')
    for path in paths:
        raw = (ROOT / path).read_bytes()
        if digest(raw) != activation['codeSha256'][path] or git_bytes(commit, path) != raw:
            raise ValueError(f'Code changed after review: {path}')


def enrollment_floor():
    paths = sorted((ROOT / STUDY / 'issued').glob('*.json'))
    if len(paths) >= COHORT_COUNT:
        return None
    return (json.loads(paths[-1].read_bytes())['targetDate'] if paths else
            json.loads((ROOT / STUDY / 'PROTOCOL.json').read_bytes())['scope']['minimumOriginDate'])


def read_origin_inputs(source_commit, now):
    raw_members = git_bytes(source_commit, 'research/universe.json')
    raw_prices = git_bytes(source_commit, 'prices/latest_prices.csv')
    universe = json.loads(raw_members)
    rows = list(csv.DictReader(io.StringIO(raw_prices.decode())))
    expected = latest_settled(now)
    if not rows or any(r['date'] != expected for r in rows):
        raise ValueError(f'Public EOD snapshot is not the latest settled session {expected}')
    if len({r['symbol'] for r in rows}) != len(rows):
        raise ValueError('Duplicate public input symbols')
    if (parse_time(universe['retrievedAt']) > now or
            any(parse_time(r['updatedAt']) > now for r in rows)):
        raise ValueError('Input publication timestamp is in the future')
    if parse_time(git('show', '-s', '--format=%cI', source_commit)) > now:
        raise ValueError('Input Git commit is in the future')
    members = universe['members']
    if not 450 <= len(members) <= 550 or not set(members) <= {r['symbol'] for r in rows}:
        raise ValueError('Public membership and EOD coverage disagree')
    return expected, members, rows, raw_members, raw_prices


def normalize_history(raw, symbol, origin):
    document = json.loads(raw)
    result = document['chart']['result'][0]
    ticker = symbol.replace('.', '-')
    if result['meta']['symbol'].upper() != ticker.upper():
        raise ValueError(f'Provider identity mismatch for {symbol}')
    # Exactly the adjusted-price basis used by v5, not the Close CSV used by
    # trend v1. Keep separate anchors as required by the frozen blend protocol.
    closes = result['indicators'].get('adjclose', [{}])[0].get(
        'adjclose', result['indicators']['quote'][0]['close'])
    timestamps = result['timestamp']
    if len(timestamps) != len(closes):
        raise ValueError('Mismatched history timestamps and closes')
    rows = []
    for stamp, price in zip(timestamps, closes):
        day = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
        if day <= origin and price is not None and math.isfinite(price) and price > 0:
            rows.append(dict(date=day, close=float(price)))
    if (len(rows) < 200 or rows[-1]['date'] != origin or
            [r['date'] for r in rows] != sorted({r['date'] for r in rows})):
        raise ValueError(f'Missing, stale, duplicate or short adjusted history: {symbol}')
    return rows


def download_history(symbol, origin):
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/' +
           quote(symbol.replace('.', '-'), safe='') + '?range=20y&interval=1d')
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'DashboardEnvironmentResearch/1.0'}),
                         timeout=25) as response:
                raw = response.read()
            at = datetime.now(timezone.utc).isoformat()
            return raw, normalize_history(raw, symbol, origin), dict(url=url, retrievedAt=at)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def collect(members, origin, directory):
    symbols = sorted(set(members) | set(PROXIES))
    histories, provenance, failures = {}, {}, {}
    raw_dir = directory / 'raw'
    raw_dir.mkdir(parents=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        pending = {executor.submit(download_history, s, origin): s for s in symbols}
        for future in concurrent.futures.as_completed(pending):
            symbol = pending[future]
            try:
                raw, history, evidence = future.result()
                stored = gzip.compress(raw, mtime=0)
                path = raw_dir / (symbol.replace('^', 'INDEX_') + '.json.gz')
                path.write_bytes(stored)
                histories[symbol] = history
                provenance[symbol] = dict(**evidence, rawSha256=digest(raw),
                    storedSha256=digest(stored), path=path.relative_to(ROOT).as_posix(),
                    normalizedSha256=digest(canonical(history)), rows=len(history),
                    firstDate=history[0]['date'], lastDate=history[-1]['date'])
            except Exception as error:
                failures[symbol] = str(error)
    if any(s not in histories for s in PROXIES) or len(set(histories) & set(members)) < 450:
        raise ValueError(f'Incomplete new provider inputs; no issue published: {failures}')
    return dict(sorted(histories.items())), dict(sorted(provenance.items())), failures


def append_components(result, origin, issued_at, input_sha, manifest_path):
    # Validate the whole transaction before writing either component archive.
    if latest_settled(parse_time(issued_at)) != origin:
        raise ValueError('Only a genuinely new issue at the latest settled origin is allowed')
    issued_path = ROOT / 'research/issued.json'
    prior = json.loads(issued_path.read_bytes())
    month_path = ROOT / 'forecasts/archive' / f'{origin[:7]}.csv'
    old_csv = month_path.read_bytes() if month_path.exists() else b''
    old_rows = list(csv.DictReader(io.StringIO(old_csv.decode()))) if old_csv else []
    vkeys = {(r['model'], r['symbol'], r['asOf'], str(r['horizon'])) for r in prior}
    tkeys = {(r['model'], r['symbol'], r['asOf'], str(r['horizon'])) for r in old_rows}
    for group, model, keys in ((result['v5'], 'environment-challenger-v5-horizon-specific', vkeys),
                               (result['trend'], 'trend-decay-v1', tkeys)):
        seen = set()
        for row in group:
            key = (row['model'], row['symbol'], row['asOf'], str(row['horizon']))
            point = float(row.get('horizonModel', row.get('base')))
            if (key in keys or key in seen or row['model'] != model or row['asOf'] != origin
                    or str(row['horizon']) != '21' or not math.isfinite(point) or point <= 0
                    or not math.isfinite(float(row['anchor'])) or float(row['anchor']) <= 0):
                raise ValueError('Duplicate or invalid component; never rewrite a first issue')
            seen.add(key)
    if not set(r['symbol'] for r in result['v5']) & set(r['symbol'] for r in result['trend']):
        raise ValueError('No common issued component cohort')
    new_v5 = [dict(r, issuedAt=issued_at, inputSha256=input_sha,
                   publicationManifest=manifest_path) for r in result['v5']]
    new_trend = [dict(r, issuedAt=issued_at) for r in result['trend']]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
    if not old_csv:
        writer.writeheader()
    elif old_csv.decode().splitlines()[0] != ','.join(FIELDS) or not old_csv.endswith(b'\n'):
        raise ValueError('Unexpected existing trend CSV format')
    writer.writerows(new_trend)
    issued_path.write_bytes(canonical(prior + new_v5))
    month_path.parent.mkdir(parents=True, exist_ok=True)
    month_path.write_bytes(old_csv + stream.getvalue().encode())
    return dict(v5RowSha256={r['symbol']: digest(canonical(r)) for r in new_v5},
                trendRowSha256={r['symbol']: digest(canonical({k: str(v) for k, v in r.items()}))
                                for r in new_trend})


def commit_only(paths, message):
    git('add', '--', *paths)
    staged = git('diff', '--cached', '--name-only').splitlines()
    if any(not (p == 'research/issued.json' or p.startswith('forecasts/archive/') or
                p.startswith(PREFIX + '/inputs/') or p.startswith(STUDY + '/issued/')) for p in staged):
        raise ValueError('Publication attempted to stage a non-research path')
    if staged:
        git('commit', '-m', message)


def publish():
    assert_state_branch()
    verify_sources()
    verify_activation(datetime.now(timezone.utc))
    # Finish a previous interrupted input commit before downloading anything.
    frozen = freeze_one()
    if frozen:
        commit_only([f'{STUDY}/issued'], 'Freeze prospective legacy 21-session blend')
    floor = enrollment_floor()
    now = datetime.now(timezone.utc)
    if floor is None or latest_settled(now) < floor:
        if frozen:
            verify_and_push()
        print(json.dumps(dict(status='waiting', nextOriginOnOrAfter=floor, recovered=frozen)))
        return
    source_commit = git('rev-parse', 'origin/main')
    origin, members, rows, raw_members, raw_prices = read_origin_inputs(source_commit, now)
    if target_start_utc(target_date(origin)) <= now:
        raise ValueError('Target has begun; never reconstruct a matured issue')
    directory = ROOT / PREFIX / 'inputs' / origin
    if directory.exists():
        raise ValueError('Input snapshot already exists; never replace a first publication')
    histories, provenance, failures = collect(members, origin, directory)
    bundle = dict(origin=origin, members=members, priceRows=rows, histories=histories)
    raw_bundle = canonical(bundle)
    bundle_path = directory / 'normalized.json.gz'
    bundle_path.write_bytes(gzip.compress(raw_bundle, mtime=0))
    (directory / 'universe.json').write_bytes(raw_members)
    (directory / 'prices.csv').write_bytes(raw_prices)
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / 'components.json'
        subprocess.run([sys.executable, str(ROOT / PREFIX / 'legacy/generate.py'),
                        str(bundle_path), str(output)], check=True)
        result = json.loads(output.read_bytes())
    issued_at = datetime.now(timezone.utc).isoformat()
    if latest_settled(parse_time(issued_at)) != origin:
        raise ValueError('A newer session closed during generation; discard this unissued run')
    manifest_path = (directory / 'publication.json').relative_to(ROOT).as_posix()
    hashes = append_components(result, origin, issued_at, digest(raw_bundle), manifest_path)
    manifest = dict(version='prospective-publication-v1', origin=origin, issuedAt=issued_at,
        inputSourceCommit=source_commit, generatorCommit=git('rev-parse', 'HEAD'),
        legacyCommit=json.loads((ROOT / PREFIX / 'SOURCE-LOCK.json').read_bytes())['legacyCommit'],
        sourceLockSha256=SOURCE_LOCK_SHA256, protocolSha256=REGISTERED_PROTOCOL_SHA256,
        normalizedSha256=digest(raw_bundle), normalizedStoredSha256=digest(bundle_path.read_bytes()),
        universeSha256=digest(raw_members), pricesSha256=digest(raw_prices),
        histories=provenance, unavailableHistories=failures,
        dependencies={k: importlib.metadata.version(k)
                      for k in ('numpy', 'scikit-learn', 'scipy', 'joblib', 'threadpoolctl')},
        pythonVersion=sys.version,
        generation={k: v for k, v in result.items() if k not in ('v5', 'trend')},
        counts=dict(v5=len(result['v5']), trend=len(result['trend'])), sourceRowHashes=hashes,
        workflow=dict(runId=os.environ.get('GITHUB_RUN_ID'), attempt=os.environ.get('GITHUB_RUN_ATTEMPT')),
        containsFutureTargetData=False, productionPromotion=False,
        limitations=['Current membership and revised adjusted history remain non-PIT training inputs.',
                     'This is a newly trained original estimator, not the retired fitted artifact.',
                     'Unavailable histories are explicit; full frozen intersection is evaluated later.'])
    (directory / 'publication.json').write_bytes(canonical(manifest))
    commit_only([str(directory.relative_to(ROOT)), 'research/issued.json',
                 f'forecasts/archive/{origin[:7]}.csv'],
                f'Issue research-only legacy 21-session components for {origin}')
    frozen = freeze_one()
    if not frozen:
        raise ValueError('New component issue was not accepted by the unchanged freezer')
    commit_only([f'{STUDY}/issued'], 'Freeze prospective legacy 21-session blend')
    verify_and_push()
    print(json.dumps(dict(status='issued_and_frozen', **frozen), sort_keys=True))


def verify_and_push():
    for path in sorted((ROOT / STUDY / 'issued').glob('*.json')):
        raw = path.read_bytes()
        snapshot = json.loads(raw)
        verify_issue_artifact('HEAD', path.relative_to(ROOT).as_posix(), raw, snapshot,
                              REGISTERED_PROTOCOL_SHA256)
        if target_start_utc(snapshot['targetDate']) <= datetime.now(timezone.utc):
            # An existing older cohort may now be mature, but a newly staged one
            # must never be pushed late. Check only files absent from the remote.
            found = subprocess.run(['git', 'cat-file', '-e', f'origin/{STATE_BRANCH}:' +
                                    path.relative_to(ROOT).as_posix()], cwd=ROOT,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if found.returncode:
                raise ValueError('New issue cannot be published after target session start')
    git('push', 'origin', f'HEAD:refs/heads/{STATE_BRANCH}')  # never force/rebase/main


if __name__ == '__main__':
    publish()
