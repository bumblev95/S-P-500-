import json
import tempfile
import unittest
from pathlib import Path

import translate_company_news as m


class TranslationTests(unittest.TestCase):
    def article(self):
        return {'id': 'news:one', 'title': 'Tesla delivery report',
                'summary': 'Tesla delivered 486,532 vehicles, above expectations.',
                'impact': {'status': 'positive', 'evidence': ['Tesla delivered 486,532 vehicles']}}

    def test_extracts_completed_event_and_keeps_opinion_as_opinion(self):
        a = self.article()
        self.assertEqual(m.short_passage(a), a['summary'])
        a['summary'] = 'Tesla delivered 486,532 vehicles, above expectations but'
        self.assertEqual(m.short_passage(a), a['title'])
        a['impact']['status'] = 'unclear'
        a['title'] = 'Should you buy Tesla?'
        self.assertEqual(m.short_passage(a), a['title'])

    def test_cache_source_changes_review_binding_and_observation_preservation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'news').mkdir()
            a = self.article(); a['publishedAt'] = '2026-10-02T20:00:00Z'
            a['observedAt'] = '2026-10-03T02:00:00Z'
            payload = {'issuers': {'1': {'articles': [a]}}, 'generatedAt': a['observedAt']}
            path = root/'news/latest.json'; path.write_text(json.dumps(payload))
            calls = []
            def translate(texts):
                calls.extend(texts)
                return ['테슬라가 차량 486,532대를 인도해 예상을 웃돌았습니다.']*len(texts)
            first = m.translate_snapshot(root, translate)
            ko = first['issuers']['1']['articles'][0]['ko']
            self.assertEqual(ko['sourceTitle'], a['title'])
            self.assertEqual(ko['sourceExcerpt'], a['summary'])
            self.assertEqual(first['generatedAt'], a['observedAt'])
            self.assertEqual(first['issuers']['1']['articles'][0]['publishedAt'], a['publishedAt'])
            m.translate_snapshot(root, translate); self.assertEqual(len(calls), 1)
            reviewed = {'news:one': {'sourceHash': m.source_hash(a), 'summary': '테슬라 인도량은 486,532대입니다.'}}
            (root/'news/korean-reviewed.json').write_text(json.dumps(reviewed))
            checked = m.translate_snapshot(root, translate)['issuers']['1']['articles'][0]['ko']
            self.assertEqual(checked['method'], 'reviewed-summary')
            latest = json.loads(path.read_text()); latest['issuers']['1']['articles'][0]['summary'] = 'Tesla delivered 400,000 vehicles, above expectations.'
            latest['issuers']['1']['articles'][0]['impact']['evidence'] = ['Tesla delivered 400,000 vehicles']
            path.write_text(json.dumps(latest))
            changed = m.translate_snapshot(root, translate)['issuers']['1']['articles'][0]['ko']
            self.assertEqual(len(calls), 2)
            self.assertEqual(changed['method'], 'machine-translation')
            self.assertNotEqual(changed['sourceHash'], checked['sourceHash'])

    def test_failed_translation_does_not_publish_english_as_korean(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'news').mkdir()
            (root/'news/latest.json').write_text(json.dumps({'issuers': {'1': {'articles': [self.article()]}}}))
            ko = m.translate_snapshot(root, lambda _: ['English only'])['issuers']['1']['articles'][0]['ko']
            self.assertEqual(ko['status'], 'unavailable')
            self.assertIn('번역을 완료하지 못했습니다', ko['summary'])
            fixed = m.translate_snapshot(root, lambda _: ['테슬라가 차량 486,532대를 인도해 예상을 웃돌았습니다.'])['issuers']['1']['articles'][0]['ko']
            self.assertEqual(fixed['status'], 'ready')

    def test_financial_smoke_check_rejects_missing_financial_meaning(self):
        good = ['이 회사는 20개의 결함이 있는 휴대폰에 대한 제품 철수를 발표했습니다.', '매출은 6% 증가했습니다.', '엔비디아는 수익 전망을 높이고 있습니다.']
        m.verify_engine(lambda _: good)
        with self.assertRaises(ValueError):
            m.verify_engine(lambda _: [good[0], '장미가 6%입니다.', good[2]])

    def test_headline_noun_disambiguation_keeps_verbs_and_nonfinancial_beats(self):
        self.assertIn('better-than-expected earnings', m.translation_input('AMETEK Earnings Beat And Higher Outlook'))
        self.assertEqual(m.translation_input('Nvidia earnings beat estimates'), 'Nvidia earnings beat estimates')
        self.assertEqual(m.translation_input('Nvidia beats a rival in chip performance'), 'Nvidia beats a rival in chip performance')

    def test_market_jargon_is_expanded_before_translation(self):
        treasury=m.translation_input('Treasury yields inch lower as investors pare back Fed rate hike bets')
        self.assertIn('interest rates on U.S. government bonds',treasury)
        self.assertIn('reduce expectations for a Federal Reserve interest rate increase',treasury)
        jobs=m.translation_input('Wall Street is looking for job growth of 84,000 after a soft labor market jobs report')
        self.assertIn('Economists expect U.S. employers to add 84,000 jobs',jobs)
        self.assertIn('weak labor market',jobs)
        self.assertIn('employment report',jobs)
        self.assertIn('Federal Reserve policy interest rate',m.translation_input('fed funds rate'))

    def test_headline_gate_rejects_cramer_and_other_obvious_fragments(self):
        for text in ['크레이머 (Cramer) 는 왜', '크레이머는 왜?', '크레이머는 “왜?”', '주가가 올랐지만',
                     '금리가 상승하면서', '미국 경제 전망 그리고', '연준의 금리 결정에 대해',
                     '주가 신고가…', '주가 신고가 (금리 상승', '주가 신고가 <unk>', 'English only']:
            with self.subTest(text=text):self.assertFalse(m.valid_korean_headline(text))
        # The general summary check retains its existing contract.
        self.assertTrue(m.valid_korean('크레이머 (Cramer) 는 왜'))

    def test_news_terms_use_literal_meanings_and_preserve_singular_and_hedge_funds(self):
        expected={
            'FOMC minutes': 'written records of the Federal Reserve monetary policy meeting',
            "FOMC's meeting minutes": 'written records of the Federal Reserve monetary policy meeting',
            'minutes from the FOMC meeting': 'written records of the Federal Reserve monetary policy meeting',
            "Federal Reserve’s last meeting minutes": 'written records of the Federal Reserve monetary policy meeting',
            'QUANT FUNDS': 'investment FUNDS using mathematical and statistical trading strategies',
            'quantitative hedge fund': 'investment hedge fund using mathematical and statistical trading strategies',
            'offshore workers': 'workers at sea', 'offshore worker': 'worker at sea',
        }
        for source,normalized in expected.items():
            with self.subTest(source=source):
                self.assertEqual(m.translation_input(source),normalized)
                self.assertEqual(m.translation_input(normalized),normalized, 'Retry/engine normalization must be idempotent')

    def test_meaning_gate_accepts_financial_and_news_synonyms(self):
        synonyms={
            'FOMC minutes': ['연준 의사록 공개를 앞두고 국채 금리 보합', '연준 회의 기록을 기다리는 투자자들',
                             '연방준비제도 정책회의의 서면 기록 공개', 'FOMC 회의록 공개 예고',
                             '연준 회의에 대한 서면 기록 발표'],
            'quant funds': ['퀀트 펀드, 시장보다 높은 수익률', '계량 투자펀드의 시장 초과 수익',
                            '통계 기반 투자 기금의 성과', '정량적 투자 전략의 성과', '양적 헤지펀드의 성과'],
            'offshore workers': ['해상 노동자 48시간 파업', '해양 시설 근로자의 임금 갈등', '바다에서 근무하는 직원들 파업'],
        }
        for source,headlines in synonyms.items():
            for headline in headlines:
                with self.subTest(source=source,headline=headline):
                    self.assertTrue(m.valid_korean_headline(headline,source))

    def test_meaning_gate_rejects_wrong_or_missing_known_source_senses(self):
        cases=[('FOMC minutes','투자자들이 FOMC 분기를 예상하며 국채 금리는 보합'),
               ('FOMC minutes','국채 금리는 보합'),
               ('FOMC minutes','회사 회의록 공개에 국채 금리는 보합'),
               ('FOMC minutes','FOMC 분기 전망과 회의록 공개'),
               ('quant funds','양자 자금은 시장을 이기는 방법'),
               ('quant funds','통계를 사용하는 양자 펀드의 성과'),
               ('quant funds','투자펀드의 성과'),
               ('offshore workers','오프셔널 노동자 48시간 파업'),
               ('offshore workers','해외 근로자의 파업')]
        for source,headline in cases:
            with self.subTest(source=source,headline=headline):
                self.assertTrue(m.valid_korean_headline(headline),'These are complete but semantically unsafe')
                self.assertFalse(m.valid_korean_headline(headline,source))
                self.assertTrue(m.valid_korean(headline),'Summary validation is unchanged')

    def test_ambiguous_words_and_excerpt_only_terms_do_not_trigger_headline_rules(self):
        cases=[('Cook rice for 20 minutes','쌀을 20분 동안 익히기'),
               ('Quantum computing funds receive new investment','양자 컴퓨팅 자금에 신규 투자'),
               ('Offshore funds face tax scrutiny','역외 펀드 세금 조사'),
               ('Offshore wind farms grow','해상 풍력 발전 확대'),
               ('Workers at an overseas office go on strike','해외 근로자 파업'),
               ('Markets are flat','시장 보합')]
        for source,headline in cases:
            with self.subTest(source=source):
                self.assertEqual(m.translation_input(source),source)
                self.assertTrue(m.valid_korean_headline(headline,source))

    def test_headline_gate_allows_nominal_headlines_and_complete_questions(self):
        for text in ['미국 주식 신고가', '인도 주식 시장이 성장하면서도 침체하는 5가지 이유',
                     '금리 상승에도 주가 강세', '주가가 오르는 이유는?', '왜 주가가 오르나?',
                     '연준, 기준금리 0.25%p 인하', '미국 주식 (S&P 500) 신고가',
                     '주가 급등…금리도 상승']:
            with self.subTest(text=text):self.assertTrue(m.valid_korean_headline(text))

    def test_simpler_headline_uses_complete_source_lead_not_trailing_teaser(self):
        title='Stocks are hitting records despite surging yields. Cramer explains why'
        self.assertEqual(m.simpler_headline_input(title),'Stock prices are at record highs despite surging yields.')
        self.assertEqual(m.simpler_headline_input(title,'Surging Treasury yields pressure the stock market.'),
                         'Stock prices are at record highs despite sharply rising bond interest rates.')
        crops='Crop stocks grow despite surging yields.'
        self.assertEqual(m.simpler_headline_input(crops,'A bumper wheat crop increased grain supplies.'),crops)
        self.assertEqual(m.simpler_headline_input('U.S. stocks rise. Cramer explains why'),'US stocks rise.')
        self.assertEqual(m.simpler_headline_input('Treasury yields rise: Fed holds rates'),
                         'interest rates on U.S. government bonds rise, Federal Reserve holds rates')


if __name__ == '__main__': unittest.main()
