"""Read-only provenance/coverage audit. Never reads target prices or scores models."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import subprocess
from pathlib import Path

from audit_prospective_blends import (ROOT, PROTOCOL_PATH, TARGET_PATTERN, audit,
    canonical, digest, git, git_bytes, list_files, parse_timestamp,
    verify_issue_artifact, target_start_utc)
from prospective_blends import REGISTERED_PROTOCOL_SHA256, target_date
from publish_prospective_components import normalize_history

PUBLICATION = 'research/joint-indicator/prospective-publication-v1'


def run(main, state, research):
    main, state, research = [git('rev-parse', ref) for ref in (main, state, research)]
    protocol = git_bytes(state, PROTOCOL_PATH)
    assert digest(protocol) == REGISTERED_PROTOCOL_SHA256
    assert protocol == git_bytes(research, PROTOCOL_PATH)
    main_paths = set(git('ls-tree', '-r', '--name-only', main).splitlines())
    cohorts = []
    for path in list_files(state):
        raw = git_bytes(state, path)
        issue = json.loads(raw)
        first = verify_issue_artifact(state, path, raw, issue, digest(protocol))
        prefix = f"{PUBLICATION}/inputs/{issue['origin']}"
        manifest_raw = git_bytes(state, f'{prefix}/publication.json')
        manifest = json.loads(manifest_raw)
        assert manifest['protocolSha256'] == digest(protocol)
        normalized_raw = git_bytes(state, f'{prefix}/normalized.json.gz')
        assert digest(normalized_raw) == manifest['normalizedStoredSha256']
        # Hash normalized bytes in chunks: loading both full 20-year JSON
        # bundles as Python objects can exceed a small research runner's RAM.
        sha = hashlib.sha256()
        with gzip.GzipFile(fileobj=io.BytesIO(normalized_raw)) as stream:
            while chunk := stream.read(1024 * 1024):
                sha.update(chunk)
        assert sha.hexdigest() == manifest['normalizedSha256']
        del normalized_raw
        assert parse_timestamp(manifest['issuedAt']) < target_start_utc(issue['targetDate'])
        for name, key in [('prices.csv', 'pricesSha256'), ('universe.json', 'universeSha256')]:
            data = git_bytes(state, f'{prefix}/{name}')
            assert digest(data) == manifest[key]
            source_path = 'prices/latest_prices.csv' if name == 'prices.csv' else 'research/universe.json'
            assert data == git_bytes(manifest['inputSourceCommit'], source_path)
        for name, evidence in manifest['histories'].items():
            stored = git_bytes(state, evidence['path'])
            assert digest(stored) == evidence['storedSha256']
            raw_history = gzip.decompress(stored)
            assert digest(raw_history) == evidence['rawSha256']
            history = normalize_history(raw_history, name, issue['origin'])
            assert digest(canonical(history)) == evidence['normalizedSha256']
            assert history[-1]['date'] == issue['origin']
            assert all(row['date'] <= issue['origin'] for row in history)
            assert parse_timestamp(evidence['retrievedAt']) <= parse_timestamp(manifest['issuedAt'])
        assert not (set(manifest['unavailableHistories']) & set(manifest['histories']))
        assert target_date(issue['origin']) == issue['targetDate']
        cohorts.append(dict(origin=issue['origin'], targetDate=issue['targetDate'],
            issueFile=path, issueFileSha256=digest(raw), firstIssueCommit=first,
            capturedAt=issue['capturedAt'], symbols=issue['cohort']['n'],
            manifestSha256=digest(manifest_raw), issuedAt=manifest['issuedAt'],
            inputSourceCommit=manifest['inputSourceCommit'], generatorCommit=manifest['generatorCommit'],
            rawHistoriesVerified=len(manifest['histories']),
            unavailableHistories=manifest['unavailableHistories'],
            workflow=manifest['workflow'],
            targetArchivePresentOnMain=TARGET_PATTERN.format(date=issue['targetDate']) in main_paths))
    for prior, current in zip(cohorts, cohorts[1:]):
        assert current['origin'] >= prior['targetDate']
    prices = git_bytes(main, 'prices/latest_prices.csv')
    price_rows = list(csv.DictReader(io.StringIO(prices.decode())))
    preserved = {}
    for suffix in ['CONTINUOUS-RESEARCH.md','PROTOCOL.json','RESULTS.md','results.json',
                   'blends/PROTOCOL.json','blends/RESULTS.md','blends/results.json','blends/FINDINGS.md']:
        p = 'research/joint-indicator/' + suffix
        preserved[p] = {'researchSha256': digest(git_bytes(research,p)),
                        'mainSha256': digest(git_bytes(main,p)) if p in main_paths else None}
    return dict(version='prospective-recovery-audit-v1', mainCommit=main,
        stateCommit=state, researchCommit=research,
        protocolSha256=digest(protocol), cohorts=cohorts,
        enrollmentAudit=audit(state),
        publicEod=dict(sha256=digest(prices), rows=len(price_rows),
                       dates=sorted({r['date'] for r in price_rows})),
        preservedResearch=preserved,
        auditCodeSha256=digest(Path(__file__).read_bytes()),
        verifierCodeSha256=digest((ROOT/'scripts/audit_prospective_blends.py').read_bytes()),
        hypothesesTested=0, scoresWritten=False, selection=None, promotion=False,
        nextAction='Keep frozen rules; wait for five non-overlapping cohorts and all exact target archives. Do not substitute Nov 27 prices for the missing Nov 23 target. Historical PIT coverage remains a separate prerequisite for new historical fitting.',
        limitations=['Provenance checks do not re-train or establish accuracy.',
                     'Current membership and revised-price training limitations remain.',
                     'No target prices read; presence checks do not certify target coverage.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--research', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.main, args.state, args.research)
    if args.output.exists():
        raise ValueError('Refusing to overwrite an audit')
    args.output.write_bytes(canonical(result))
    print(json.dumps({'cohorts': len(result['cohorts']), 'scoresWritten': False,
                      'sha256': digest(canonical(result))}))
