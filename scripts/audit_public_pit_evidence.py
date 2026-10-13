"""Offline individual-notice supplementation. No model, network, or production writer."""
from __future__ import annotations
import argparse
import copy
import csv
import gzip
import io
import json
import re
from collections import Counter
from pathlib import Path
from datetime import datetime, time
from audit_fja_sp500_quarantine import compare_event, official_membership, reconcile_official
from build_pit_sp500_inputs import audit_bundle
from pit_sp500_inputs import InputError, PITInputs, NY, VERSION, canonical, conservative_known_at, session_open, sha256, timestamp
from research_merger_lifecycle import LifecycleInputs

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'research/joint-indicator/pit-public-evidence-v1'
SEED = ROOT / 'research/joint-indicator/pit-inputs-v1'
LIFECYCLE = ROOT / 'research/joint-indicator/merger-lifecycle-v1'
FJA = ROOT / 'research/joint-indicator/pit-quarantine-fja-v1'
EVIDENCE_VERSION = 'pit-public-evidence-v1'

def read(folder, name):
    return json.loads((folder / name).read_bytes())

def source_text(folder, source):
    capture = read(folder, source['path'])
    return '\n'.join(c.get('text', '') for c in capture['response']['content'] if c['type'] == 'text')

def verify_lock(folder):
    lock = read(folder, 'source-lock.json')
    if lock['version'] != EVIDENCE_VERSION or lock['researchOnly'] is not True:
        raise InputError('Research-only source lock required')
    for relative, expected in lock['preservedFiles'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or sha256(path.read_bytes()) != expected:
            raise InputError('Earlier file changed: ' + relative)
    sources = {}
    for source in lock['newCaptures']:
        path = (folder / source['path']).resolve()
        if not path.is_relative_to(folder) or sha256(path.read_bytes()) != source['sha256']:
            raise InputError('Captured evidence changed: ' + source['sourceId'])
        if source['originalHTTPPayloadAvailable'] or source['historicalRevisionVintageCertified']:
            raise InputError('Extracted-page evidence cannot certify original HTTP/vintage')
        sources[source['sourceId']] = source
    return lock, sources

def end_of_day(day):
    return datetime.combine(datetime.fromisoformat(day).date(), time(23,59,59), NY).isoformat()

def notice_date(value):
    value=value.replace('.','').replace('Sept ','Sep ')
    for form in ('%B %d, %Y','%b %d, %Y'):
        try:return datetime.strptime(value,form).date().isoformat()
        except ValueError:pass
    raise InputError('Unrecognized exact notice date: '+value)

def verify_notice_row(row, text):
    publication=re.search(r'NEW YORK, ([A-Za-z.]+ \d{1,2}, \d{4})',text)
    if publication is None:raise InputError('Original notice publication date absent')
    if row['evidenceLocator'].startswith('L') and '-' not in row['evidenceLocator']:
        raw=row['evidenceText'].split(':',1)[1].strip().split('|')[0].strip()
        if not raw:
            # A row-spanned date is inherited only from the preceding table row
            # in these same exact captured bytes; never from another notice.
            before=text[:text.index(row['evidenceText'])]
            dated=[l for l in before.splitlines() if '| S&P 500 ' in l and l.split(':',1)[1].strip().split('|')[0].strip()]
            if not dated:raise InputError('Missing date for row-spanned notice')
            raw=dated[-1].split(':',1)[1].strip().split('|')[0].strip()
    else:
        raw=re.search(r'L\d+: ([A-Za-z.]+ \d{1,2}, \d{4})',row['evidenceText'])[1]
    if notice_date(raw)!=row['effectiveDate']:
        raise InputError('Effective date disagrees with exact table row')
    venue=re.search(r'\((NYSE|NASD|Nasdaq)\s*:\s*'+re.escape(row['ticker'])+r'\)',text)
    expected='NYSE' if venue and venue[1]=='NYSE' else 'NASDAQ' if venue else None
    if expected!=row['venue']:raise InputError('Venue disagrees with exact notice paragraph')
    return notice_date(publication[1])

def normalize(folder=FOLDER):
    folder = Path(folder).resolve()
    lock, captures = verify_lock(folder)
    data = copy.deepcopy(read(SEED, 'inputs.json'))
    data.update(datasetId=EVIDENCE_VERSION, frozenAt=lock['createdAt'], researchOnly=True)
    for source in captures.values():
        if source['captureStatus'] != 'extracted_page':
            continue
        data['sources'].append(dict(sourceId=source['sourceId'], uri=source['uri'],path=source['path'],
            sha256=source['sha256'],rawSha256=source['sha256'],retrievedAt=source['retrievedAt'],
            temporalQuality='dated_notice',publicationPrecision='day',publicationDate=source['publicationDate'],
            availabilityFloor=conservative_known_at(source['publicationDate']),availabilityEvidence=source['provenanceNote'],
            captureRepresentation=source['representation'],originalHTTPPayloadAvailable=False,
            historicalRevisionVintageCertified=False))
    registry = {s['securityId'] for s in data['securities']}
    def register(sid):
        if sid not in registry:
            registry.add(sid)
            data['securities'].append(dict(securityId=sid,provisional=True,
                note='Individual notice lineage only; no permanent issue ID or certified continuity.'))
    def add(event_id, sid, kind, source, effective, locator, value):
        register(sid)
        row = dict(eventId=event_id, securityId=sid, kind=kind, sourceId=source,
            effectiveAt=effective, knownAt=conservative_known_at(captures[source]['publicationDate']),
            evidenceLocator=locator, value=value, evidenceScope='individual_dated_notice_not_complete_history')
        if kind == 'membership': row['indexId'] = 'SP500'
        data['events'].append(row)
    observations = read(folder, 'membership-observations.json')['observations']
    keys = set()
    for row in observations:
        sid, source = row['securityId'], row['sourceId']
        if source not in captures or captures[source]['captureStatus'] != 'extracted_page':
            raise InputError('Failed/unknown capture cannot be normalized')
        key = (source, row['ticker'], row['action'])
        if key in keys: raise InputError('Duplicate notice observation')
        keys.add(key)
        text = source_text(folder, captures[source])
        if row['evidenceText'] not in text:
            raise InputError('Exact extracted row locator no longer resolves')
        if row['action'] not in {'Addition','Deletion'}:
            raise InputError('Unknown notice action')
        tokens = [row['ticker'], row['companyName'], row['sectorLabel'], row['action'], 'S&P 500']
        if not all(token in row['evidenceText'] for token in tokens):
            raise InputError('Normalized fields disagree with source row')
        if verify_notice_row(row,text)!=captures[source]['publicationDate']:
            raise InputError('Publication date disagrees with exact release paragraph')
        effective = session_open(row['effectiveDate']).isoformat()
        eid = 'public-' + row['observationId']
        add(eid+'-membership',sid,'membership',source,effective,row['evidenceLocator'],row['action']=='Addition')
        if not re.search(r'\((?:NYSE|NASD|Nasdaq)\s*:\s*'+re.escape(row['ticker'])+r'\)', text):
            raise InputError('Alias venue not supported by notice paragraph')
        add(eid+'-symbol',sid,'symbol',source,effective,row['evidenceLocator']+'; named exchange in notice paragraph',
            dict(symbol=row['ticker'],venue=row['venue']))
        if row['ticker']=='SOLV' and source=='sp-20240327':
            if 'will be added to GICS Industrials Sector' not in text or 'April 3' not in text:
                raise InputError('Solventum footnote missing')
            for day,name in [('2024-04-01','Industrials'),('2024-04-03','Health Care')]:
                add(eid+'-sector-'+day,sid,'sector',source,session_open(day).isoformat(),'L85 explicit spin-off sector footnote',
                    dict(name=name,taxonomy='GICS',taxonomyVersion='notice-2024-03-27-footnote'))
        else:
            if '*' in row['sectorLabel']: raise InputError('Unresolved sector footnote')
            add(eid+'-sector',sid,'sector',source,effective,row['evidenceLocator'],
                dict(name=row['sectorLabel'],taxonomy='GICS',taxonomyVersion='notice-label-'+captures[source]['publicationDate']))
    dfs_sid = next(r['securityId'] for r in observations if r['ticker']=='DFS')
    add('public-dfs-terminal',dfs_sid,'delisting','dfs-20250519-terms',end_of_day('2025-05-18'),
        'Item 2.01 L98-L103; merger closing differs from index deletion and filing date',
        dict(reason='acquired',settlementStatus='unresolved',statedSuccessorShareRatio=1.0192,
             note='Closing/conversion terms observed; actual settlement, fractional cash, distributions and horizon quotes missing.'))
    data['events'][-1]['effectivePrecision']='day_conservative_end'
    # Retirement requested pre-open May 19. It is not visible until the later filing clock.
    add('public-dfs-alias-retired',dfs_sid,'symbol','dfs-20250519-terms',session_open('2025-05-19').isoformat(),
        'Item 3.01 L118-L121 NYSE withdrawal/suspension request',dict(symbol=None,venue='NYSE'))
    # Identity observations never enter the verified identity-event table.
    for row in read(folder,'identity-observations.json')['observations']:
        if row['identityVerifiedForPIT'] or row['permanentSecurityId'] is not None:
            raise InputError('CIK/class observation cannot certify permanent issue identity')
        if row['publicationDate'] != captures[row['clockSourceId']]['publicationDate']:
            raise InputError('Filing clock/observation mismatch')
        clock_text=source_text(folder,captures[row['clockSourceId']])
        if not re.search(r'Filing Date\s*\nL\d+:\s*\nL\d+: '+re.escape(row['publicationDate']),clock_text):
            raise InputError('Filing availability date not supported by saved index')
    lifecycle = copy.deepcopy(read(LIFECYCLE,'lifecycle-inputs.json'))
    by_source = {s['sourceId']:s for s in data['sources']}
    lifecycle_sources=['dfs-20250519-terms','cof-20250518-ir','psky-20250807-8k','psky-20250807-release',
        'para-20250807-8k','para-20250807-index','psky-20250807-index','snps-20250717']
    lifecycle['sources'].extend(copy.deepcopy(by_source[s]) for s in lifecycle_sources)
    def observed(oid,source,day,locator,**terms):
        lifecycle['observations'].append(dict(observationId=oid,sourceId=source,knownAt=by_source[source]['availabilityFloor'],
            effectiveAt=end_of_day(day),effectivePrecision='day_conservative_end',evidenceLocator=locator,
            allowedUse='diagnostic_only',status='unresolved',identityStatus='provisional_unverified',totalReturnFactor=None,**terms))
    observed('dfs-exchange-terms','dfs-20250519-terms','2025-05-18','L98-L103; Item 3.01 L118-L121',
        observedTicker='DFS',originSecurityId=dfs_sid,referenceEventId='public-dfs-terminal',statedSuccessorTicker='COF',
        statedSuccessorSharesPerShare=1.0192,fractionalTreatment='cash in lieu after account-level aggregation; paid value unavailable',
        note='Original share extinguished; successor quote is not an original-security price. No distribution/settlement history or horizon valuation.')
    observed('dfs-closing-release','cof-20250518-ir','2025-05-18','L7,L12',observedTicker='DFS',
        note='Issuer announced closing May 18; does not supply the exchange ratio or settlement certificate. May 19 filing terms not backdated.')
    observed('paramount-elections','psky-20250807-8k','2025-08-07','L161-L182',observedTicker='PARA',
        additionalEvidenceSourceIds=['para-20250807-8k','para-20250807-index','psky-20250807-index'],
        statedSuccessorTicker='PSKY',oldIssuerCIK='0000813828',newIssuerCIK='0002041610',
        classBCashElectionUSD=15.0,classBStockElectionShares=1.0,classBCashProrationStated=0.60925910,
        classACashElectionUSD=23.0,classAStockElectionShares=1.5333,
        note='Separate Aug 6 pre-closing conversion and Aug 7 merger/election steps. No assumed investor election, settled units, permanent issue mapping, or final return.')
    observed('psky-trading-release','psky-20250807-release','2025-08-07','Opening release paragraphs',observedTicker='PSKY',
        note='New Class B trading observed; does not prove S&P effective membership or simple permanent-security continuity from PARA.')
    observed('ansys-closing','snps-20250717','2025-07-17','Acquisition completion paragraph',observedTicker='ANSS',
        note='Acquisition completion independently observed; no terms/settlement/full lifecycle valuation inferred from this release.')
    return data, lifecycle

def build_supplemental(folder, data, lifecycle, pit_report):
    lock, captures = verify_lock(folder)
    candidates=read_gzip(FJA/'observations.json.gz')['events']
    official=official_membership(data)
    comparisons=[dict(candidateId=c['candidateId'],date=c['effectiveDateCandidate'],ticker=c['ticker'],action=c['action'],
        historicalKnownAt=None,securityId=None,**compare_event(c,official)) for c in candidates]
    partitions={status:[c for c in comparisons if c['status']==status] for status in ['match','conflict','unconfirmed']}
    reference=read(FJA,'coverage-audit.json')
    origin_rows=[]
    priority={r['origin']:r for r in lock['chosenOrigins']}
    for row in reference['origins']:
        origin=row['origin'];cutoff=session_open(origin)
        # Candidate change windows are reused verbatim; no newly invented candidate population.
        window=row['changeWindow']
        eligible=[e for e in official if timestamp(e['knownAt'])<cutoff and timestamp(e['effectiveAt'])<=cutoff]
        selected=[c for c in candidates if (window['fromExclusive'] is None or c['effectiveDateCandidate']>window['fromExclusive'])
                  and c['effectiveDateCandidate']<=window['throughInclusive']]
        counts=Counter(compare_event(c,eligible)['status'] for c in selected)
        origin_rows.append(dict(origin=origin,priority=priority.get(origin,{}).get('priority'),reason=priority.get(origin,{}).get('reason'),
            ready=False,window=window,candidateWindowCount=len(selected),
            candidateWindowComparisonCounts={s:counts[s] for s in ['match','conflict','unconfirmed']},
            visibleOfficialNoticeFacts=len(eligible),originalBlockers=row['blockers'],
            extraBlockers=['new_captures_lack_original_HTTP_payload_and_archival_revision_certification']))
    return dict(version=EVIDENCE_VERSION,researchOnly=True,modelTrainingAllowed=False,productionChangesAllowed=False,
        readyOriginCount=pit_report['readyOriginCount'],originCount=pit_report['originCount'],
        lifecycleReadyOriginCount=0,realComputedOutcomeCount=0,sourceResearchHead=lock['sourceResearchHead'],
        guardPR54Head=lock['guardPR54Head'],guardScope='Separate input-only PR stacked on #25; no modification, merge, or release of #54. Its quarantine remains required.',
        preservedFileCount=len(lock['preservedFiles']),newCapturedPageCount=sum(s['captureStatus']=='extracted_page' for s in captures.values()),
        failedCaptureIds=[s['sourceId'] for s in captures.values() if s['captureStatus']!='extracted_page'],
        reusedPITSourceCount=len(read(SEED,'inputs.json')['sources']),officialMembershipFactCount=len(official),
        addedMembershipFactCount=len(read(folder,'membership-observations.json')['observations']),
        verifiedPermanentIdentityCount=0,identityObservationCount=len(read(folder,'identity-observations.json')['observations']),
        sectorStructureObservations=read(folder,'sector-structure-observations.json')['observations'],
        lifecycleObservationCount=len(lifecycle['observations']),normalizedLifecycleActionCount=len(lifecycle['actions']),
        candidateCount=len(candidates),previousCandidateComparisonCounts=reference['candidateComparisonCounts'],
        candidateComparisonCounts={s:len(partitions[s]) for s in partitions},candidateComparisonPartitions=partitions,
        officialMembershipComparisons=reconcile_official(official,candidates),origins=origin_rows,
        acquisitionLimits=lock['rawHTTPAcquisitionLimit'],
        finalCompanyGICS2023MapAcquired=False,
        metricBlockers=['no_certified_full_origin_baselines','no_complete_membership_sector_alias_identity_history',
            'no_original_availability_price_vintages_including_delisted_issues','no_full_distribution_settlement_rights_and_horizon_valuations',
            'no_new_original_HTTP_payload_or_archival_revision_certification'],
        blockedResearch=['survivorship_safe_126_and_252_day_model_training_and_joint_MAPE_direction_selection',
            'complete_cohort_merger_delisting_total_return_metrics','adapter_production_promotion'],
        noChangePolicy='No study fitting/scoring, production forecast, TOP3, trading rule, deployment, paid subscription, or scheduled acquisition.')

def read_gzip(path): return json.loads(gzip.decompress(path.read_bytes()))

def freeze(files):
    # Preflight every target before any mutation; existing different bytes fail.
    for path,raw in files.items():
        if path.exists() and path.read_bytes()!=raw:raise InputError('Frozen file differs: '+str(path))
    for path,raw in files.items():
        if not path.exists():path.write_bytes(raw)

def run(folder=FOLDER, verify=False):
    folder=Path(folder).resolve()
    lock,_=verify_lock(folder)
    data,lifecycle=normalize(folder)
    normalized={folder/'inputs.json':canonical(data),folder/'lifecycle-inputs.json':canonical(lifecycle)}
    if verify:
        for path,raw in normalized.items():
            if path.read_bytes()!=raw:raise InputError('Normalization replay differs: '+path.name)
    else:freeze(normalized)
    # Original PIT manifest semantics, including origin research head, remain intact.
    manifest=dict(version=VERSION,researchOnly=True,sourceResearchHead=read(SEED,'manifest.json')['sourceResearchHead'],
        researchDependencyHead=lock['sourceResearchHead'],evidenceVersion=EVIDENCE_VERSION,
        implementationFiles={name:sha256((ROOT/name).read_bytes()) for name in
            ['scripts/audit_public_pit_evidence.py','scripts/test_public_pit_evidence.py','.github/workflows/validate-public-pit-evidence.yml']},
        preservedFiles=lock['preservedFiles'],bundleFiles={p.relative_to(folder).as_posix():sha256(p.read_bytes())
            for p in sorted(folder.rglob('*')) if p.is_file() and p.name not in
            {'manifest.json','coverage-audit.json','supplemental-audit.json','origin-coverage.csv','README.md','FINDINGS.md','verification.json'}})
    if verify:
        if (folder/'manifest.json').read_bytes()!=canonical(manifest):raise InputError('Manifest replay differs')
    else:freeze({folder/'manifest.json':canonical(manifest)})
    PITInputs.load(folder)
    LifecycleInputs.load(folder)
    report,_=audit_bundle(folder)
    supplemental=build_supplemental(folder,data,lifecycle,report)
    out=io.StringIO(newline=''); writer=csv.writer(out,lineterminator='\n')
    writer.writerow(['origin','priority','candidate_window_count','match','conflict','unconfirmed','visible_official_facts','ready'])
    for row in supplemental['origins']:
        c=row['candidateWindowComparisonCounts']
        writer.writerow([row['origin'],row['priority'],row['candidateWindowCount'],c['match'],c['conflict'],c['unconfirmed'],row['visibleOfficialNoticeFacts'],'false'])
    files={folder/'coverage-audit.json':canonical(report),folder/'supplemental-audit.json':canonical(supplemental),
           folder/'origin-coverage.csv':out.getvalue().encode()}
    if verify:
        for path,raw in files.items():
            if path.read_bytes()!=raw:raise InputError('Audit replay differs: '+path.name)
    else:freeze(files)
    return supplemental

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,default=FOLDER)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--build',action='store_true');mode.add_argument('--verify',action='store_true')
    args=parser.parse_args(argv)
    try:
        report=run(args.folder,verify=args.verify)
        print(json.dumps({k:report[k] for k in ['version','addedMembershipFactCount','candidateComparisonCounts','readyOriginCount','lifecycleReadyOriginCount','preservedFileCount']}))
        return 0
    except (InputError,KeyError,OSError,ValueError) as e:
        print(str(e));return 2

if __name__=='__main__':raise SystemExit(main())
