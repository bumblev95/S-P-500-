from datetime import date
import unittest

from build_congress_chart_data import produce


HOUSE = 'https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/12345.pdf'
SENATE_PATH = '/search/view/ptr/01234567-01ab-42cd-ab12-0123456789ab/'
SENATE = 'https://efdsearch.senate.gov' + SENATE_PATH
TODAY = date(2026, 11, 26)


def capitol(**fields):
    return {
        'chamber': 'house', 'ticker': 'BRK.B', 'filer_name': 'Test Filer',
        'transaction_date': '2026-10-05', 'filing_date': '2026-10-28',
        'transaction_type': 'Sale (partial)', 'security_type': 'stock',
        'amount_range_label': '$1,001 - $15,000', 'doc_url': HOUSE, 'asset_type': 'ST', **fields,
    }


def insider(**fields):
    return {
        'chamber': 'senate', 'ticker': 'AAPL', 'member': 'Test Senator',
        'transaction_date': '10/5/2026', 'filed_date': '10/28/2026', 'action': 'buy',
        'asset': 'Apple Inc. Common Stock', 'amount_range': '$1,001 - $15,000',
        'owner': 'Spouse', 'filing_id': 'efd-' + SENATE_PATH, **fields,
    }


class CongressChartDataTest(unittest.TestCase):
    def test_symbol_range_side_and_exact_duplicates(self):
        rows = [
            capitol(), capitol(), capitol(amount_range_label='$1,001'),
            capitol(ticker='NVDA'), capitol(ticker='BRK'),
            capitol(transaction_date='2026-12-05'), capitol(filing_date='2026-11-27'),
            capitol(doc_url=HOUSE.replace('house.gov', 'house.gov.example')),
            capitol(filing_date='2026-10-01'),
        ]
        data, counts, base = produce(rows, [], {'BRK-B', 'NVDA'}, TODAY)
        self.assertEqual(set(data), {'BRK-B'})
        self.assertEqual(base, 2)
        self.assertEqual(counts['house'], 2)
        first, second = data['BRK-B']
        self.assertEqual(first['amount'], '$1,001 - $15,000')
        self.assertNotIn('amount', second)
        self.assertEqual(first['side'], 'sell')
        self.assertTrue(first['partial'])
        self.assertEqual(first['delayDays'], 23)
        self.assertEqual(first['filingUrl'], HOUSE)

    def test_recover_senate_direction_without_guessing_and_keep_option_type(self):
        rows = [
            capitol(chamber='senate', ticker='AAPL', transaction_type='Stock', doc_url=SENATE),
            capitol(ticker='GOOGL', security_type='call_option', transaction_type='Purchase'),
        ]
        extra = [
            insider(), insider(), insider(ticker='GOOG', asset='Alphabet call option'),
        ]
        data, counts, _ = produce(rows, extra, {'AAPL', 'GOOG', 'GOOGL'}, TODAY)
        self.assertEqual(counts['senate'], 1)
        self.assertEqual(data['AAPL'][0]['owner'], 'spouse')
        self.assertEqual(data['AAPL'][0]['filingUrl'], SENATE)
        self.assertEqual(data['AAPL'][0]['disclosedDate'], '2026-10-28')
        self.assertTrue(data['GOOGL'][0]['option'])
        self.assertNotIn('GOOG', data)

    def test_overlap_between_sources(self):
        rows = [capitol(
            chamber='senate', ticker='AAPL', transaction_type='Purchase', doc_url=SENATE,
        )]
        data, counts, base = produce(rows, [insider(amount_range='$1,001 – $15,000')], {'AAPL'}, TODAY)
        self.assertEqual(len(data['AAPL']), 1)
        self.assertEqual(counts['senate'], 1)
        self.assertEqual(base, 1)


if __name__ == '__main__':
    unittest.main()
