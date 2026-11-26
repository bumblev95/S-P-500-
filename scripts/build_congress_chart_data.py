"""Publish daily stock-chart views of public US congressional PTRs."""

import argparse
import csv
from collections import Counter, defaultdict
from datetime import date, datetime
import io
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

CAPITOL = 'https://www.capitolstockwatch.com/data/trades.json'
INSIDER = 'https://insiderwatch.ai/api/data/congress-trades.csv'
LEGACY_SYMBOL = 'NVDA'
SOURCES = [
    {'name': 'CapitolStockWatch', 'url': 'https://www.capitolstockwatch.com/export'},
    {'name': 'InsiderWatch, insiderwatch.ai', 'url': 'https://insiderwatch.ai/congress-disclosure-lag'},
]
HOUSE = r'https://disclosures-clerk\.house\.gov/public_disc/ptr-pdfs/\d{4}/\d+\.pdf'
SENATE = r'https://efdsearch\.senate\.gov/search/view/ptr/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/'
AMOUNT = r'(?:\$[\d,]+\s*[-–—]\s*\$[\d,]+|(?:Over|More than) \$[\d,]+)'
ACTION = {'purchase': 'buy', 'sale (full)': 'sell', 'sale (partial)': 'sell'}
OWNER = {
    'sp': 'spouse', 'spouse': 'spouse', 'self': 'self', 'jt': 'joint',
    'joint': 'joint', 'dc': 'dependent', 'child': 'dependent',
}
OPTIONS = {'option': '옵션', 'call_option': '콜옵션', 'put_option': '풋옵션'}


def download(url, source_file):
    if source_file:
        raw = source_file.read_bytes()
    else:
        request = Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; SP500ResearchDashboard/1.0)',
        })
        with urlopen(request, timeout=45) as response:
            raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError(f'Disclosure feed exceeded size limit: {url}')
    return raw.decode('utf-8-sig')


def csv_rows(url, source_file, required):
    reader = csv.DictReader(io.StringIO(download(url, source_file), newline=''))
    if not required <= set(reader.fieldnames or ()):
        raise ValueError(f'Unexpected disclosure feed schema: {url}')
    return list(reader)


def day(value, pattern):
    return datetime.strptime(value, pattern).date()


def produce(capitol, insider, tickers, today):
    by_symbol = defaultdict(list)
    seen = set()
    primary_trades = set()
    counts = Counter()
    baseline_non_nvda = 0

    def add(row, *, ticker, trade_date, filing_date, side, chamber, member, filing, source):
        symbol = (ticker or '').strip().upper().replace('.', '-')
        if not symbol or symbol not in tickers or symbol == LEGACY_SYMBOL:
            return False
        try:
            pattern = '%Y-%m-%d' if source == 0 else '%m/%d/%Y'
            trade, submitted = day(trade_date, pattern), day(filing_date, pattern)
        except (ValueError, TypeError):
            return False
        if not (trade <= submitted <= today) or not (member or '').strip() or not side:
            return False
        if not re.fullmatch(HOUSE if chamber == 'house' else SENATE, filing):
            return False
        amount_field = 'amount_range_label' if source == 0 else 'amount_range'
        amount = (row.get(amount_field) or '').strip()
        owner = OWNER.get((row.get('owner') or '').strip().lower())
        amount_key = tuple(re.findall(r'\d+', amount.replace(',', '')))
        key = filing, symbol, trade, side, amount_key
        if source == 0:
            primary_trades.add(key)
        elif key in primary_trades:
            return False
        identity = (key, owner, row.get('comment'), row.get('asset_name'),
                    row.get('security_type'), row.get('strike_price'), row.get('expiration_date'))
        if identity in seen:
            return False
        seen.add(identity)
        event = {
            'member': member.strip(), 'chamber': chamber, 'side': side,
            'tradeDate': trade.isoformat(), 'disclosedDate': submitted.isoformat(),
            'filingUrl': filing, 'delayDays': (submitted - trade).days,
        }
        if re.fullmatch(AMOUNT, amount, re.I):
            event['amount'] = amount
        if owner:
            event['owner'] = owner
        if source == 0:
            security = row['security_type']
            if security in OPTIONS:
                event['option'] = True
                event['optionDescription'] = OPTIONS[security]
            if row['transaction_type'].lower() == 'sale (partial)':
                event['partial'] = True
        by_symbol[symbol].append(event)
        counts[chamber] += 1
        return True

    for row in capitol:
        chamber = row['chamber']
        security = row['security_type']
        asset_type = row['asset_type']
        is_equity = security == 'stock' and asset_type in {'ST', 'Stock', 'CS', 'PS', None}
        if chamber not in {'house', 'senate'} or not (is_equity or security in OPTIONS):
            continue
        baseline_non_nvda += add(
            row, ticker=row['ticker'], trade_date=row['transaction_date'],
            filing_date=row['filing_date'], side=ACTION.get(row['transaction_type'].lower()),
            chamber=chamber, member=row['filer_name'], filing=row['doc_url'], source=0,
        )

    # The second feed has a direction for recent Senate records missing from the first.
    # Only matching official filings and identical normalized events are deduplicated.
    for row in insider:
        if row['chamber'] != 'senate' or row['action'] not in {'buy', 'sell'}:
            continue
        if re.search(r'\b(options?|bonds?|muni|municipal|notes?|warrants?|fund|etf)\b', row['asset'], re.I):
            continue
        filing_id = row['filing_id']
        if not filing_id.startswith('efd-/'):
            continue
        add(
            row, ticker=row['ticker'], trade_date=row['transaction_date'],
            filing_date=row['filed_date'], side=row['action'], chamber='senate',
            member=row['member'], filing='https://efdsearch.senate.gov' + filing_id[4:],
            source=1,
        )
    return by_symbol, counts, baseline_non_nvda


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capitol-json', type=Path)
    parser.add_argument('--insider-csv', type=Path)
    parser.add_argument('--forecasts', type=Path, default=Path('forecasts/latest.json'))
    parser.add_argument('--output', type=Path, default=Path('data/congress/by-symbol'))
    args = parser.parse_args()
    capitol = json.loads(download(CAPITOL, args.capitol_json))
    if not isinstance(capitol, list):
        raise ValueError('Unexpected CapitolStockWatch feed schema')
    insider = csv_rows(INSIDER, args.insider_csv, {
        'chamber', 'ticker', 'member', 'transaction_date', 'filed_date', 'action',
        'asset', 'amount_range', 'owner', 'filing_id',
    })
    tickers = json.loads(args.forecasts.read_text(encoding='utf-8'))['stocks'].keys()
    by_symbol, counts, base = produce(capitol, insider, tickers, date.today())

    # Fail the job before replacing a previously published snapshot if a feed is truncated.
    if len(by_symbol) < 100 or base < 1000 or counts['senate'] < 40 or len(insider) < 500:
        raise ValueError(f'Unexpected disclosure coverage: {len(by_symbol)=}, {base=}, {counts=}')
    events = [event for stock in by_symbol.values() for event in stock]
    metadata = {
        'asOf': max(event['disclosedDate'] for event in events),
        'oldestTradeDate': min(event['tradeDate'] for event in events),
        'sources': SOURCES, 'licenseUrl': 'https://creativecommons.org/licenses/by/4.0/',
        'tradeCount': len(events), 'chambers': dict(counts),
        'symbols': {symbol: len(by_symbol[symbol]) for symbol in sorted(by_symbol)},
    }
    prior_file = args.output / 'index.json'
    if prior_file.exists():
        prior = json.loads(prior_file.read_text(encoding='utf-8'))
        if metadata['asOf'] < prior['asOf'] or len(events) < prior['tradeCount'] * 0.8:
            raise ValueError('Disclosure feed is older or materially smaller than the published snapshot')

    args.output.mkdir(parents=True, exist_ok=True)
    for symbol, trades in sorted(by_symbol.items()):
        trades.sort(key=lambda event: (
            event['tradeDate'], event['disclosedDate'], event['member'], event['filingUrl'],
        ), reverse=True)
        write_json(args.output / f'{symbol}.json', {'symbol': symbol, 'events': trades})
    for path in args.output.glob('*.json'):
        if path.stem not in by_symbol and path.stem != 'index':
            path.unlink()
    write_json(prior_file, metadata)
    print(f"{len(events)} trades on {len(by_symbol)} symbols through {metadata['asOf']} ({dict(counts)})")


if __name__ == '__main__':
    main()
