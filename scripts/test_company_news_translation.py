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


if __name__ == '__main__': unittest.main()
