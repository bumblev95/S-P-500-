"""Offline, hash-pinned SEC coverage diagnosis. Does not write production inputs."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import build_research_inputs as sec
from sec_fallbacks import PARSER_VERSION, POLICY_HASH, diagnostics, PREDECESSORS, parse_cik

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'research/sec-audit/2026-10-01'


def digest(raw): return hashlib.sha256(raw).hexdigest()


def sources(folder=FOLDER):
    manifest = json.loads((folder/'manifest.json').read_text())
    payloads = {}
    for name, item in manifest['sources'].items():
        compressed = (folder/item['path']).read_bytes()
        if digest(compressed) != item['gzipSha256']: raise ValueError('Compressed source changed: '+name)
        raw = gzip.decompress(compressed)
        if digest(raw) != item['sha256']: raise ValueError('Source changed: '+name)
        if name.endswith('.json'): payloads[name] = json.loads(raw)
        elif name == 'baseline-parser.py': payloads[name] = raw.decode()
    return manifest, payloads


def audit(root=ROOT, folder=FOLDER):
    manifest, payloads = sources(folder)
    base = manifest['baselineCommit']
    if manifest['sources']['baseline-inputs.json']['sha256'] != manifest['baselineInputsHash'] or manifest['sources']['baseline-universe.json']['sha256'] != manifest['baselineUniverseHash']:
        raise ValueError('Baseline input checkpoint changed')
    baseline, universe = payloads['baseline-inputs.json'], payloads['baseline-universe.json']
    previous = payloads['comparison-universe.json']
    if universe['members'] != previous['members'] or universe['sourceHash'] != previous['sourceHash']:
        raise ValueError('Universe changed; this audit only isolates SEC coverage')
    stocks = dict(baseline['stocks']);details = {};issuers = {}
    for symbol in baseline['secCoverage']['missingSymbols']:
        cik = universe['members'][symbol]['cik']
        payload = payloads[f'CIK{cik:010d}.json']
        if parse_cik(payload.get('cik')) != cik: raise ValueError('Audit source issuer identity mismatch')
        policy = PREDECESSORS.get(cik)
        predecessor = payloads[f"CIK{policy['sourceCIK']:010d}.json"] if policy else None
        rows = sec.financial_history(payload, predecessor, as_of=manifest['asOfDate'])
        detail = diagnostics(payload, rows, sec.TAGS['revenue'], predecessor)
        details[str(cik)] = detail
        issuers[symbol] = dict(cik=cik, **detail, latestEvidence=rows[-1]['evidence'] if rows else [],
                               latestFeatures={k:rows[-1][k] for k in sec.STOCK_FIELDS} if rows else None,
                               mappingEvidence=policy if policy else None)
        stocks[symbol] = dict(cik=cik, rows=rows)
    wanted = {s:v['cik'] for s,v in universe['members'].items()}
    coverage = sec.sec_coverage(wanted, stocks, {}, details)
    unchanged = [s for s in wanted if s not in issuers]
    if any(stocks[s] != baseline['stocks'][s] for s in unchanged): raise ValueError('Audit rewrote covered issuer history')
    counts = ('targetIssuers', 'usableIssuers', 'targetTickers', 'usableTickers')
    code_hashes = {name:digest((root/'scripts'/name).read_bytes()) for name in
                   ('build_research_inputs.py', 'sec_fallbacks.py', 'import_sec_companyfacts.py', 'audit_sec_coverage.py')}
    return dict(schemaVersion=1, baselineCommit=base, asOfDate=manifest['asOfDate'],
                parserVersion=PARSER_VERSION, policyHash=POLICY_HASH, codeHashes=code_hashes,
                sourceManifestHash=digest((folder/'manifest.json').read_bytes()),
                universe=dict(membersUnchanged=True, sourceHashUnchanged=True, sourceHash=universe['sourceHash']),
                baselineCoverage={k:baseline['secCoverage'][k] for k in counts},
                offlineCoverage={k:coverage[k] for k in (*counts, 'fallbackIssuers', 'missingSymbols')},
                retainedCoveredTickers=len(unchanged), issuers=issuers,
                limitations=[manifest['scope'],
                    'Offline parser/coverage replay, not a production refresh or predictive performance test.',
                    'Filed dates are reconstructed from current CompanyFacts; not a certified vintage feed.',
                    'Bank denominator is explicitly net interest plus noninterest income, before credit provisions; tax-equivalent/non-GAAP adjustments are not guessed.',
                    'XOM predecessor facts stop at the conversion and are never admitted before its mapping filing date.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Require byte-identical reproduction of the committed report')
    args = parser.parse_args()
    report = json.dumps(audit(), indent=2, ensure_ascii=False, allow_nan=False)+'\n'
    target = FOLDER/'report.json'
    if args.check:
        if target.read_text() != report: raise SystemExit('SEC audit report differs; inspect the change before regenerating')
    else: target.write_text(report)
    print(json.loads(report)['offlineCoverage'])
