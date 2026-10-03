"""Reviewed annual CompanyFacts fallbacks. No custom tags or guessed issuer aliases."""
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date

PARSER_VERSION = 'sec-annual-v2-reviewed-fallbacks'
FORMS = ('10-K', '10-Q', '10-K/A', '10-Q/A')
INCLUDING_TAX = 'RevenueFromContractWithCustomerIncludingAssessedTax'
# This tag is only a partial revenue disclosure for some banks. Never enable it
# globally or change TAGS, which is also imported by frozen quarterly experiments.
REVENUE_ISSUERS = {91419: 'SJM', 878927: 'ODFL', 1035002: 'VLO',
                   1535527: 'CRWD', 1637459: 'KHC'}
BANK_ISSUERS = {35527: 'FITB', 92230: 'TFC', 1281761: 'RF'}
BANK_TAGS = ('InterestIncomeExpenseNet', 'NoninterestIncome')
BANK_BASIS = 'reported_net_interest_plus_noninterest_income'
BANK_SOURCES = {
    35527: 'https://www.sec.gov/Archives/edgar/data/35527/000003552726000124/R5.htm',
    92230: 'https://www.sec.gov/Archives/edgar/data/92230/000009223026000030/R5.htm',
    1281761: 'https://www.sec.gov/Archives/edgar/data/1281761/000128176126000019/R5.htm',
}
PREDECESSORS = {2115436: dict(
    id='xom-redomiciliation-2026', symbol='XOM', sourceCIK=34088,
    targetCIK=2115436, effectiveDate='2026-07-01', filed='2026-07-01',
    accession='0001193125-26-291990',
    source='https://www.sec.gov/Archives/edgar/data/2115436/000119312526291990/d71068d8k12b.htm')}
UNSUPPORTED = {
    1841666: 'custom_or_dimensioned_revenue_not_in_companyfacts',
    1601712: 'custom_retailer_share_adjustment_required',
    2089271: 'quarterly_only_no_annual_revenue',
}


def payload_hash(payload):
    """Canonical JSON hash, independent of HTTP/cache whitespace."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


POLICY_HASH = payload_hash(dict(revenue=REVENUE_ISSUERS, revenueTag=INCLUDING_TAX,
                                banks=BANK_ISSUERS, bankTags=BANK_TAGS, bankBasis=BANK_BASIS,
                                bankSources=BANK_SOURCES, forms=FORMS, annualDays=[330,400],
                                predecessors=PREDECESSORS, unsupported=UNSUPPORTED))


def parse_cik(value):
    # SEC returns both JSON integers and decimal strings for newer registrants.
    if isinstance(value, bool): raise ValueError('Invalid SEC CIK')
    if isinstance(value, int): cik = value
    elif isinstance(value, str) and re.fullmatch(r'\d{1,10}', value): cik = int(value)
    else: raise ValueError('Invalid SEC CIK')
    if not 0 < cik < 10**10: raise ValueError('Invalid SEC CIK')
    return cik


def qualified(row, annual=True):
    value = row.get('val')
    if row.get('form') not in FORMS or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    try:
        end, filed = date.fromisoformat(row['end']), date.fromisoformat(row['filed'])
        if end > filed: return False
        if annual and not 330 <= (end-date.fromisoformat(row['start'])).days <= 400: return False
    except (KeyError, TypeError, ValueError): return False
    return True


def usd_rows(payload, tag):
    return payload.get('facts', {}).get('us-gaap', {}).get(tag, {}).get('units', {}).get('USD', [])


def as_fact(row, tag, cik, rank, fallback):
    return dict(name='revenue', tag=tag, rank=rank, filed=row['filed'], end=row['end'],
                start=row['start'], value=row['val'], accession=row.get('accn'),
                form=row['form'], sourceCIK=cik, fallback=fallback)


def expand_facts(payload, facts, rank):
    """Only reviewed CIKs; exact same-filing arithmetic, never partial/gross income."""
    try: cik = parse_cik(payload.get('cik'))
    except ValueError: return facts
    if cik in REVENUE_ISSUERS:
        facts += [as_fact(r, INCLUDING_TAX, cik, rank, 'standard_revenue_tag')
                  for r in usd_rows(payload, INCLUDING_TAX) if qualified(r)]
    if cik in BANK_ISSUERS:
        groups = defaultdict(lambda: defaultdict(list))
        for tag in BANK_TAGS:
            for r in usd_rows(payload, tag):
                if qualified(r) and r.get('accn'):
                    groups[(r['start'], r['end'], r['filed'], r['accn'], r['form'])][tag].append(r)
        for key, components in sorted(groups.items()):
            # Conflicting same-context values are unresolved; don't pick one.
            if any(tag not in components or len({r['val'] for r in components[tag]}) != 1 for tag in BANK_TAGS): continue
            rows = [components[tag][0] for tag in BANK_TAGS]
            value = sum(r['val'] for r in rows)
            if not math.isfinite(value) or value <= 0: continue
            row = dict(rows[0], val=value)
            fact = as_fact(row, BANK_BASIS, cik, rank, 'bank_reported_components')
            fact['components'] = [as_fact(r, tag, cik, rank, 'bank_reported_components') for tag, r in zip(BANK_TAGS, rows)]
            facts.append(fact)
    return facts


def attach_predecessor(payload, predecessor, facts, extract):
    cik = parse_cik(payload.get('cik'))
    policy = PREDECESSORS.get(cik)
    if not policy or parse_cik(predecessor.get('cik')) != policy['sourceCIK']:
        raise ValueError('Unreviewed predecessor SEC issuer identity')
    # Only original pre-conversion disclosures. Later parent/subsidiary statements
    # aren't interchangeable, even if the old registrant continues filing.
    for fact in extract(predecessor):
        if fact['filed'] <= policy['effectiveDate'] and fact['end'] < policy['effectiveDate']:
            facts.append(dict(fact, knownDate=max(fact['filed'], policy['filed']),
                              fallback='reviewed_predecessor', mapping=policy))
    return facts


def evidence_for(fact, detailed=False):
    rows = fact.get('components', [fact])
    result = []
    for row in rows:
        evidence = dict(tag=row['tag'], filed=row['filed'], periodEnd=row['end'], accession=row['accession'])
        if detailed:
            evidence.update(taxonomy='us-gaap', unit='USD', sourceCIK=row.get('sourceCIK'),
                            periodStart=row.get('start'), value=row['value'], form=row.get('form'))
        result.append(evidence)
    return result


def diagnostics(payload, rows, baseline_tags, predecessor=None):
    cik = parse_cik(payload.get('cik'))
    baseline = sum(qualified(r) and r['val'] > 0 for tag in baseline_tags for r in usd_rows(payload, tag))
    including = sum(qualified(r) and r['val'] > 0 for r in usd_rows(payload, INCLUDING_TAX))
    components = {tag: sum(qualified(r) for r in usd_rows(payload, tag)) for tag in BANK_TAGS}
    annual_flow = sum(qualified(r) for tag in ('NetIncomeLoss', 'NetCashProvidedByUsedInOperatingActivities') for r in usd_rows(payload, tag))
    if baseline: reason = 'supported_standard_annual_revenue'
    elif cik in REVENUE_ISSUERS and including: reason = 'standard_revenue_tag_not_selected'
    elif cik in BANK_ISSUERS: reason = 'bank_revenue_components_not_selected'
    elif cik in PREDECESSORS: reason = 'successor_cik_without_annual_history'
    else: reason = UNSUPPORTED.get(cik, 'no_supported_standard_annual_revenue')
    fallbacks = sorted({f for row in rows for f in row.get('fallbacks', [])})
    sources = {str(cik): payload_hash(payload)}
    if predecessor is not None: sources[str(parse_cik(predecessor.get('cik')))] = payload_hash(predecessor)
    latest = rows[-1] if rows else None
    return dict(parserVersion=PARSER_VERSION, policyHash=POLICY_HASH, reason=reason,
                state='fallback_applied' if fallbacks else ('standard' if rows else 'missing'),
                fallbacks=fallbacks, sourcePayloadHashes=sources,
                baselineAnnualRevenueFacts=baseline, includingTaxAnnualRevenueFacts=including,
                bankComponentAnnualFacts=components, otherAnnualFlowFacts=annual_flow,
                historyRows=len(rows), latestAvailableDate=latest['availableDate'] if latest else None,
                latestPeriodEnd=latest['periodEnd'] if latest else None)
