"""Current company events for display only; never inputs to forecasts/backtests.

SEC metadata classifies filings, not sentiment or the contents of unparsed news.
Offline replay uses captured submissions with their ORIGINAL observation time.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit

from build_forecasts import atomic_json
from build_research_inputs import request, sec_identity
from research_universe import load_universe
from sec_fallbacks import PREDECESSORS, parse_cik, payload_hash

ROOT = Path(__file__).resolve().parents[1]
PARSER = 'company-events-v1'
WINDOW_DAYS = 180
MAX_EVENTS = 20
FORMS = {'10-K', '10-K/A', '10-Q', '10-Q/A', '20-F', '20-F/A',
         '40-F', '40-F/A', '6-K', '6-K/A', '8-K', '8-K/A', '8-K12B', 'DEF 14A'}
# Neutral translations of SEC Form 8-K headings. Item 7.01 / 8.01 do NOT prove
# a guidance change, regulatory action, dividend or buyback announcement.
ITEMS = {
    '1.01': ('contract', '주요 계약 체결·변경'),
    '1.02': ('contract', '주요 계약 종료'),
    '1.03': ('corporate', '파산·관리 절차'),
    '1.05': ('security', '중요 사이버보안 사고'),
    '2.01': ('corporate', '자산 인수·처분 완료'),
    '2.02': ('earnings', '실적·재무 현황'),
    '2.03': ('capital', '금융채무 발생'),
    '2.04': ('capital', '채무 조기상환·증가 사유'),
    '2.05': ('corporate', '사업 정리 비용'),
    '2.06': ('report', '중요 자산 손상'),
    '3.01': ('corporate', '상장 기준 관련 통지'),
    '3.02': ('capital', '미등록 주식 발행'),
    '3.03': ('capital', '주주 권리 변경'),
    '4.01': ('governance', '외부 감사인 변경'),
    '4.02': ('report', '기존 재무보고 신뢰성 관련'),
    '5.01': ('governance', '지배권 변경'),
    '5.02': ('governance', '이사·경영진·보상 변경'),
    '5.03': ('governance', '정관·회계연도 변경'),
    '5.07': ('governance', '주주 투표 결과'),
    '7.01': ('disclosure', '투자자 안내'),
    '8.01': ('disclosure', '기타 주요 사항'),
}


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else (default if default is not None else {})


def stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Invalid calendar date')
    return date.fromisoformat(value)


def symbol(value):
    return value.upper().replace('.', '-')


def describe(form, item_ids):
    if form.startswith('8-K'):
        topics = [(i, ITEMS[i]) for i in item_ids if i in ITEMS]
        if form == '8-K12B':
            title, category = '법인·상장 전환 공시', 'corporate'
        elif topics:
            title = ' · '.join(label for _, (_, label) in topics[:2]) + ' 공시'
            category = topics[0][1][0]
        else:
            title, category = '주요 사항 공시', 'disclosure'
        summary = '공시 항목: ' + ' · '.join(label for _, (_, label) in topics) if topics else '회사가 주요 사항을 SEC에 공시했습니다.'
    else:
        base = form.removesuffix('/A')
        title = {'10-K': '연간 보고서', '10-Q': '분기 보고서', '20-F': '해외 기업 연간 보고서',
                 '40-F': '해외 기업 연간 보고서', '6-K': '해외 기업 주요 사항 보고',
                 'DEF 14A': '주주총회 의결권 자료'}[base]
        category = 'governance' if base == 'DEF 14A' else 'report'
        summary = '회사가 ' + title + '를 SEC에 제출했습니다.'
    if form.endswith('/A'):
        title += ' · 정정'
    return title, category, summary


def parse_submissions(payload, expected_cik, observed_at, now):
    if parse_cik(payload.get('cik')) != expected_cik:
        raise ValueError('Submissions issuer CIK mismatch')
    observed = stamp(observed_at)
    if not observed or observed > now:
        raise ValueError('Invalid source observation time')
    recent = payload.get('filings', {}).get('recent')
    required = ('accessionNumber', 'filingDate', 'form', 'primaryDocument')
    if not isinstance(recent, dict) or any(not isinstance(recent.get(k), list) for k in required):
        raise ValueError('Missing submissions columns')
    length = len(recent['form'])
    optional = ('reportDate', 'acceptanceDateTime', 'items')
    if any(not isinstance(recent.get(k), list) or len(recent[k]) != length
           for k in required + tuple(k for k in optional if k in recent)):
        raise ValueError('Unaligned submissions columns')
    events, rejected, seen = [], {}, {}
    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1
    for i in range(length):
        form = recent['form'][i]
        if form not in FORMS:
            continue
        accession, document = recent['accessionNumber'][i], recent['primaryDocument'][i]
        try:
            filed = day(recent['filingDate'][i])
            if filed > min(now.date(), observed.date()):
                reject('future_filing'); continue
            if (now.date() - filed).days > WINDOW_DAYS:
                continue
            if not isinstance(accession, str) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
                raise ValueError('Invalid accession')
            if not isinstance(document, str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:htm|html|txt)', document, re.I):
                raise ValueError('Invalid primary document')
            accepted = recent.get('acceptanceDateTime', [''] * length)[i]
            if accepted and (not stamp(accepted) or stamp(accepted) > min(now, observed)):
                reject('invalid_or_future_acceptance'); continue
            raw_items = recent.get('items', [''] * length)[i]
            if not isinstance(raw_items, str) or (raw_items and not re.fullmatch(r'\d\.\d{2}(?:\s*,\s*\d\.\d{2})*', raw_items)):
                raise ValueError('Invalid items')
            item_ids = list(dict.fromkeys(raw_items.replace(' ', '').split(','))) if raw_items else []
            report = recent.get('reportDate', [''] * length)[i]
            if report:
                day(report)
                if report > filed.isoformat():
                    raise ValueError('Report date after filing')
        except (ValueError, TypeError):
            reject('invalid_row'); continue
        title, category, summary = describe(form, item_ids)
        # Submissions for the reviewed XOM successor include a predecessor's
        # 10-Q. Only that evidenced predecessor may change the archive CIK;
        # an accession prefix is otherwise a filing agent, NOT an issuer alias.
        archive_cik = expected_cik
        policy = PREDECESSORS.get(expected_cik)
        if policy and accession.startswith(f'{policy["sourceCIK"]:010d}-'):
            archive_cik = policy['sourceCIK']
        event = dict(id='sec:' + accession, date=filed.isoformat(), dateKind='filed',
                     title=title, category=category, summary=summary, form=form,
                     items=item_ids, reportDate=report or None, acceptanceAt=accepted or None,
                     sourceCIK=expected_cik, archiveCIK=archive_cik, observedAt=observed_at,
                     source={'name': 'SEC EDGAR', 'url': f'https://www.sec.gov/Archives/edgar/data/{archive_cik}/{accession.replace("-", "")}/{document}'})
        if accession in seen and seen[accession] != event:
            raise ValueError('Conflicting duplicate accession')
        if accession not in seen:
            events.append(event); seen[accession] = event
    events.sort(key=lambda e: (e['date'], e['acceptanceAt'] or '', e['id']), reverse=True)
    return events[:MAX_EVENTS], rejected


def release_events(rows, ticker, now):
    result = []
    for row in rows:
        try:
            published = day(row['availableDate'])
            observed = stamp(row.get('firstRetrievedAt'))
            source = urlsplit(row['sourceUrl'])
            host = source.hostname
            if (not observed or observed > now or published > now.date()
                    or (now.date() - published).days > WINDOW_DAYS
                    or published > observed.date() or source.scheme != 'https'
                    or host not in {'nvidianews.nvidia.com', 'www.microsoft.com'}):
                continue
            if row.get('symbol') != ticker or row.get('basis') != 'GAAP' or row.get('currency') != 'USD':
                continue
            revenue = row['revenue']
            if isinstance(revenue, bool) or not isinstance(revenue, (float, int)) or not math.isfinite(revenue) or revenue <= 0:
                continue
            period = day(row['periodEnd']).isoformat()
            if period > published.isoformat():
                continue
        except (KeyError, ValueError, TypeError):
            continue
        details = [{'label': '분기 종료일', 'value': period},
                   {'label': 'GAAP 매출', 'value': f'${revenue:,.0f} million'}]
        guidance = row.get('nextQuarterRevenue')
        has_guidance = (not isinstance(guidance, bool) and isinstance(guidance, (float, int))
                        and math.isfinite(guidance) and guidance > 0)
        if has_guidance:
            details.append({'label': '회사 다음 분기 매출 전망', 'value': f'${guidance:,.0f} million'})
        result.append(dict(id=f'release:{ticker}:{row["fiscalYear"]}:Q{row["quarter"]}',
                           date=published.isoformat(), dateKind='published', category='earnings',
                           title=f'{row["fiscalYear"]} 회계연도 {row["quarter"]}분기 실적 발표',
                           summary='분기 실적' + ('과 회사의 다음 분기 매출 전망' if has_guidance else '') + '을 공개했습니다.',
                           details=details, observedAt=row['firstRetrievedAt'], sourceHash=row.get('sourceSha256'),
                           source={'name': ticker + ' 회사 원문', 'url': row['sourceUrl']}))
    return result


def calendar_events(root, members, now):
    """Yahoo dates are explicitly estimates, never promoted to company-confirmed."""
    path = root / 'fundamentals/latest_fundamentals.csv'
    result = {}
    if not path.exists():
        return result
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        ticker = symbol(row.get('symbol', ''))
        if ticker not in members:
            continue
        observed = stamp(row.get('updatedAt'))
        try:
            planned = day(row.get('nextEarningsDate'))
        except (ValueError, TypeError):
            continue
        if (not observed or not row.get('source', '').startswith('Yahoo')
                or not 0 <= (now - observed).total_seconds() <= 8 * 86400
                or not 0 <= (planned - now.date()).days <= 120 or row.get('error')):
            continue
        result[ticker] = [dict(id='earnings-estimate:' + ticker + ':' + planned.isoformat(),
                              date=planned.isoformat(), dateKind='estimated', category='earnings',
                              title='실적 발표 예상일', summary='Yahoo 제공 예상 일정입니다. 회사가 확정한 발표일과 다를 수 있습니다.',
                              observedAt=row['updatedAt'], source={'name': 'Yahoo Finance · 예상 일정',
                              'url': f'https://finance.yahoo.com/quote/{ticker}/calendar/'})]
    return result


def captured(root, cik, now):
    cache = root / f'research/source-cache/events/CIK{cik:010d}.json'
    if cache.exists():
        saved = read(cache)
        if saved.get('sourceHash') != payload_hash(saved.get('payload')):
            raise ValueError('Captured submissions hash mismatch')
        return saved['payload'], saved['observedAt']
    # Reuse the two already reviewed official audit captures without refreshing
    # their acquiredAt or pretending a cached download was a successful request.
    audit = root / 'research/sec-audit/2026-10-01'
    entry = read(audit / 'manifest.json').get('sources', {}).get(f'submissions-CIK{cik:010d}.json')
    if entry:
        raw = gzip.decompress((audit / entry['path']).read_bytes())
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Audit submissions hash mismatch')
        return json.loads(raw), entry['acquiredAt']
    return None, None


def build(root=ROOT, download=True, now=None):
    fixed_now = now
    clock = lambda: fixed_now or datetime.now(timezone.utc)
    now = clock()
    current = now.isoformat()
    universe = load_universe(root)
    members = {symbol(s): v for s, v in universe['members'].items()}
    groups = {}
    for ticker, member in members.items():
        groups.setdefault(parse_cik(member['cik']), []).append(ticker)
    old = read(root / 'events/latest.json')
    state = read(root / 'events/request-state.json')
    issuers, attempts, errors = {}, 0, []
    blocked_until = stamp(state.get('blockedUntil'))
    unavailable = 'backoff' if blocked_until and blocked_until > now else None
    if download and not unavailable:
        try:
            sec_identity()
        except ValueError:
            unavailable = 'contact_not_configured'
    releases = read(root / 'research/earnings.json').get('issuers', {})
    consecutive_failures = 0
    for cik, tickers in sorted(groups.items()):
        now = clock()
        current = now.isoformat()
        prior = old.get('issuers', {}).get(str(cik), {})
        usable_prior = old.get('parserVersion') == PARSER and prior.get('cik') == cik
        sec = dict(prior.get('sec', {})) if usable_prior else {}
        events = [e for e in prior.get('events', []) if e.get('id', '').startswith('sec:')] if usable_prior else []
        payload, observed, fresh_request = None, None, False
        status = unavailable or (sec.get('status', 'not_collected') if not download else 'unavailable')
        if download and not unavailable:
            attempts += 1
            try:
                payload = request(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
                now = clock()
                current = now.isoformat()
                observed, fresh_request = current, True
            except Exception as exc:
                status = 'access_denied' if isinstance(exc, HTTPError) and exc.code in (401, 403, 429) else 'request_failed'
                errors.append({'cik': cik, 'code': status})
                consecutive_failures += 1
                if status == 'access_denied' or consecutive_failures >= 3:
                    unavailable = 'backoff'
                    state = {'blockedUntil': (now + timedelta(hours=24 if status == 'access_denied' else 1)).isoformat(), 'reason': status}
            finally:
                time.sleep(.3)  # At most ~3.3 requests/s, one request per CIK.
        if payload is None and not events:
            try:
                payload, observed = captured(root, cik, now)
            except (ValueError, KeyError, OSError, json.JSONDecodeError):
                errors.append({'cik': cik, 'code': 'invalid_capture'})
        if payload is not None:
            try:
                parsed, rejected = parse_submissions(payload, cik, observed, now)
                events = parsed
                status = 'ready' if fresh_request else ('captured' if not download else status)
                sec.update(lastSuccessAt=observed, sourceHash=payload_hash(payload), rejectedRows=rejected)
                if fresh_request:
                    consecutive_failures = 0
                    atomic_json(root / f'research/source-cache/events/CIK{cik:010d}.json',
                                {'observedAt': observed, 'sourceHash': sec['sourceHash'], 'payload': payload})
            except (ValueError, TypeError, KeyError):
                status = 'invalid_response'
                errors.append({'cik': cik, 'code': status})
        sec.update(status=status, checkedAt=current if fresh_request or (download and attempts and status in {'access_denied', 'request_failed'}) else sec.get('checkedAt'),
                   sourceUrl=f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
        for ticker in tickers:
            events += release_events(releases.get(ticker, []), ticker, now)
        events = [e for e in events if 0 <= (now.date() - day(e['date'])).days <= WINDOW_DAYS]
        events = sorted({e['id']: e for e in events}.values(), key=lambda e: (e['date'], e['id']), reverse=True)[:MAX_EVENTS]
        issuers[str(cik)] = dict(cik=cik, name=members[tickers[0]]['name'], tickers=tickers, sec=sec, events=events)
    if not unavailable and download:
        state = {}
    ready = [v for v in issuers.values() if v['sec']['status'] == 'ready']
    now = clock()
    current = now.isoformat()
    payload = dict(schemaVersion=1, parserVersion=PARSER, generatedAt=current, windowDays=WINDOW_DAYS,
                   universe={'sourceHash': universe.get('sourceHash'), 'retrievedAt': universe.get('retrievedAt')},
                   symbols={s: str(v['cik']) for s, v in members.items()}, issuers=issuers,
                   upcoming=calendar_events(root, members, now),
                   collection={'mode': 'online' if download else 'offline', 'requests': attempts,
                               'targetIssuers': len(groups), 'freshIssuers': len(ready),
                               'issuersWithEvents': sum(bool(v['events']) for v in issuers.values()),
                               'targetTickers': len(members), 'freshTickers': sum(len(v['tickers']) for v in ready),
                               'blockedReason': unavailable, 'errors': errors},
                   limitations=['Display-only current events; not forecast features or historical backtest inputs.',
                                'SEC filing dates are not assumed to be event occurrence or earnings announcement dates.',
                                '8-K items classify disclosures only; no inferred guidance change, price impact or sentiment.',
                                'Original quarterly-release details cover NVDA/MSFT only. Yahoo calendar dates are estimates.',
                                'Missing, stale and failed collection do not mean that the company had no events.'])
    atomic_json(root / 'events/latest.json', payload)
    if download:
        atomic_json(root / 'events/request-state.json', state)
    print(json.dumps(payload['collection'], ensure_ascii=False))
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Replay captured sources without network access')
    build(download=not parser.parse_args().offline)
