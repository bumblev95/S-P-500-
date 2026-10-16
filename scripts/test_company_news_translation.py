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
            'North Sea offshore workers': 'North Sea workers at sea',
            'Wood Group offshore worker': 'Wood Group worker at sea',
            'contrarian investment funds': 'against prevailing market sentiment investment funds',
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
            'Wood Group offshore workers': ['해상 노동자 48시간 파업', '해양 시설 근로자의 임금 갈등', '바다에서 근무하는 직원들 파업'],
            'contrarian funds': ['역발상 투자펀드의 성과', '주류에 반대하는 펀드의 전략', '시장 흐름을 거스르는 투자',
                                '시장 정서에 반하는 투자 전략'],
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
               ('Wood Group offshore workers','오프셔널 노동자 48시간 파업'),
               ('Wood Group offshore workers','해외 근로자의 파업'),
               ('contrarian funds','역동적 투자펀드의 성과'),
               ('contrarian funds','시장에 반대하는 역동적 투자펀드')]
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
               ('Offshore workers at a software outsourcing company','소프트웨어 회사의 해외 외주 노동자'),
               ('Wood Group offshore workers provide outsourced software services','우드 그룹 해외 외주 노동자의 소프트웨어 서비스'),
               ('Offshore workers','해외 노동자'),
               ('Contrarian artists challenge tradition','통념에 반대하는 예술가'),
               ('Workers at an overseas office go on strike','해외 근로자 파업'),
               ('Markets are flat','시장 보합')]
        for source,headline in cases:
            with self.subTest(source=source):
                self.assertEqual(m.translation_input(source),source)
                self.assertTrue(m.valid_korean_headline(headline,source))

    def test_observed_live_quant_translation_still_rejects_wrong_contrarian_meaning(self):
        source="How quant funds beat the market by being 'early, contrarian and right'"
        wrong="수학 및 통계적 거래 전략을 이용한 투자펀드가 '초기, 역동적이고 올바른'로 시장을 이길 수 있는 방법"
        self.assertFalse(m.valid_korean_headline(wrong,source))
        self.assertIn('against prevailing market sentiment',m.translation_input(source))

    def test_observed_live_fomc_translation_rejects_record_high_sense_of_minutes(self):
        source='Treasury yields are broadly flat as investors anticipate FOMC minutes'
        wrong='미국 정부 채권 금리율은 투자자들이 연방준비은행의 통화정책 회의에 대한 기록적인 기록을 예상하기 때문에 대체로 일정합니다.'
        self.assertTrue(m.valid_korean_headline(wrong))
        self.assertFalse(m.valid_korean_headline(wrong,source))

    def test_headline_gate_allows_nominal_headlines_and_complete_questions(self):
        for text in ['미국 주식 신고가', '인도 주식 시장이 성장하면서도 침체하는 5가지 이유',
                     '금리 상승에도 주가 강세', '주가가 오르는 이유는?', '왜 주가가 오르나?',
                     '연준, 기준금리 0.25%p 인하', '미국 주식 (S&P 500) 신고가',
                     '주가 급등…금리도 상승']:
            with self.subTest(text=text):self.assertTrue(m.valid_korean_headline(text))

    def test_first_time_adverb_needs_a_predicate_but_nominal_headlines_remain_valid(self):
        for text in ['포트 후드 총기 사격단은 2차 세계대전 이후 처음으로',
                     '미군, 2차 세계대전 이후 최초로.', '미군 사형 집행, “처음으로!”']:
            with self.subTest(text=text):
                self.assertFalse(m.valid_korean_headline(text))
                self.assertTrue(m.valid_korean(text), 'Summary validation is unchanged')
        for text in ['미군, 2차 세계대전 이후 첫 총살형 집행 예정',
                     '포트 후드 총격범 총살형, 미군에서는 전쟁 이후 처음',
                     '미군 사상 최초', '처음으로 공개된 연준 의사록',
                     '미군이 전쟁 이후 처음으로 총살형을 집행한다',
                     '이번 총살형은 전쟁 이후 처음이다']:
            with self.subTest(text=text):self.assertTrue(m.valid_korean_headline(text))

    def test_simpler_headline_expands_trailing_first_for_without_losing_either_clause(self):
        lead='Fort Hood shooter to be executed by firing squad'
        tail='a first for US military since World War Two'
        expected=('Fort Hood gunman will be executed by firing squad. '
                  'This will be the first such event for US military since World War Two.')
        for separator in [' - ', ' — ', ' – ', ': ', '; ']:
            with self.subTest(separator=separator):
                self.assertEqual(m.simpler_headline_input(lead+separator+tail),expected)
        self.assertEqual(m.simpler_headline_input(lead+'. - '+tail),expected)
        self.assertEqual(m.simpler_headline_input('U.S. firm wins a contract - a first for the company'),
                         'U.S. firm wins a contract. This is the first such event for the company.')
        self.assertEqual(m.simpler_headline_input('Stocks rise - investors await earnings'),
                         'Stocks rise, investors await earnings')

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



class ContextTranslationTests(unittest.TestCase):
    def fixture(self):
        return json.loads((Path(__file__).parent/'fixtures/market-news-context.json').read_text())['cases']

    def test_exact_historical_failures_and_reviewed_corrections(self):
        for case in self.fixture():
            a, good = case['article'], case['expected']
            with self.subTest(source=a['title']):
                self.assertEqual(m.hashlib.sha256((a['title']+'\n'+a['sourceExcerpt']).encode()).hexdigest(), a['sourceHash'])
                self.assertFalse(m.valid_korean_headline(a['headlineKo'],a['title'],a['sourceExcerpt'])
                                 and m.valid_korean_summary(a['summaryKo'],a['sourceExcerpt'],a['title']))
                self.assertTrue(m.valid_korean_headline(good['headlineKo'],a['title'],a['sourceExcerpt']))
                self.assertTrue(m.valid_korean_summary(good['summaryKo'],a['sourceExcerpt'],a['title']))

    def test_context_guards_accept_synonyms_and_preserve_other_meanings(self):
        cases = [
            ('An equal-weight index of stocks', '동일가중 주가지수'),
            ('An equal weighted ETF', '종목별 같은 비중으로 투자하는 ETF'),
            ('Physical crude oil delivery', '실물 원유 인도'),
            ("The ‘real’ price of oil", '원유의 실제 가격'),
            ('A stock selloff after weak sales', '매출 부진에 주식 매도세'),
            ('A stock sell-off after weak sales', '매출 부진에 증시 급락'),
            ('Military strikes hit refineries', '군의 공습으로 정유시설 피격'),
            ('Military strikes continue while railway strikes disrupt travel', '군의 공습 계속…철도 파업으로 운행 차질'),
            ("The Bank of England governor meets the prime minister", '영란은행 총재와 총리 회동'),
            ("The head of the country's central bank speaks", '중앙은행 수장의 발언'),
            ('The governor of the Bank of France speaks', '프랑스 중앙은행 총재 발언'),
            ('Fed governor speaks on rates', '연준 이사의 금리 발언'),
            ('Texas governor meets central bank officials', '텍사스 주지사와 중앙은행 관계자 회동'),
            ('Russian oil workers go on strike', '러시아 석유 노동자 파업'),
            ('Iranian workers strike after military attacks', '군의 공격 이후 이란 노동자 파업'),
            ('A baseball player strikes out', '야구 선수가 삼진으로 물러났다'),
            ('A striking change in military strategy', '군사 전략의 눈에 띄는 변화'),
            ('Russia strikes a deal to end the war', '러시아, 전쟁 종식 합의 체결'),
            ('Lightning strikes on a military base', '군사 기지에 낙뢰 발생'),
            ('Retailers plan a stock selloff to clear unsold inventory', '소매업체, 미판매 재고 정리 판매 계획'),
            ('Investors buy equal-weight gold bars', '투자자들이 같은 무게의 금괴를 매수한다'),
            ('Analysts downgrade the stock to Equal Weight', '애널리스트, 주식 투자의견 중립으로 하향'),
            ('Two boxes have equal weight', '두 상자의 무게가 같다'),
            ('Oil stocks rally on earnings', '석유 관련주 실적 호조에 상승'),
            ('The real price of oil adjusted for inflation', '물가를 반영한 실질 유가'),
            ('A warehouse inventory sell-off', '창고 재고 정리 판매'),
            ('Revenue rose after the selloff in stocks', '주식 매도세 이후 매출 증가'),
        ]
        for source, korean in cases:
            with self.subTest(source=source):
                self.assertTrue(m.valid_korean_headline(korean,source))
                self.assertTrue(m.valid_korean_summary(korean,source))
        # These ambiguous inputs must not be silently rewritten.
        for source,_ in cases[11:]:
            if source.startswith(('Revenue','Fed ')): continue
            self.assertEqual(m.translation_input(source),source)

    def test_normalization_keeps_roles_ownership_and_is_idempotent(self):
        cases={
            'Equal-weight stocks': 'investment allocation with the same portfolio share for each stock stocks',
            "The ‘real’ price of oil": 'The actual price of oil',
            'Physical oil': 'crude oil for physical delivery',
            'AI stock sell-off': 'AI stock market price decline',
            'Military strikes': 'Military attacks',
            'A military strike': 'A military attack',
            'a missile strike on a refinery': 'a missile attack on a refinery',
            'striking energy sites after Russian attacks': 'attacking energy sites after Russian attacks',
            'French central bank governor': 'French central bank chief',
            "The head of France's central bank": "The chief of France's central bank",
            'private equity-owned companies': 'companies owned by private investment funds',
            'release diesel stocks': 'release stored diesel reserves',
        }
        for source,expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(m.translation_input(source),expected)
                self.assertEqual(m.translation_input(expected),expected)

    def test_dangling_comparatives_and_field_specific_source(self):
        for text in ['영국 경제 성장률은 예상보다','영국 경제 성장률은 “예상보다!”','주가 상승률은 전년보다.']:
            self.assertFalse(m.valid_korean_headline(text))
            self.assertFalse(m.valid_korean_summary(text))
        for text in ['예상보다 높은 성장률','주가가 예상보다 높다','전년보다 빠른 성장']:
            self.assertTrue(m.valid_korean_headline(text))
        self.assertTrue(m.valid_korean_headline('시장 전망 발표','Markets outlook', 'Central bank governor warns of risks.'))
        self.assertTrue(m.valid_korean_summary('재정 적자를 줄일 수 있다.','The deficit can be reduced.', 'Central bank governor speaks'))
        self.assertFalse(m.valid_korean_summary('중앙은행 총리가 말했다.',"The head of the country's central bank speaks."))

    def test_summary_requires_complete_clause_and_stock_fixing_means_manipulation(self):
        self.assertTrue(m.valid_korean('월스트리트는 코어위브 주가가 다시 하락하면서'))
        self.assertFalse(m.valid_korean_summary('월스트리트는 코어위브 주가가 다시 하락하면서'))
        self.assertTrue(m.valid_korean_summary('코어위브 주가가 하락하면서 미국 증시는 혼조세다.'))
        self.assertTrue(m.valid_korean_summary('높은 금리에도 주가 상승'))
        source='Stock fixing scandal could affect global indexes'
        self.assertFalse(m.valid_korean_headline('주식 고정 스캔들이 글로벌 지표에 영향',source))
        self.assertTrue(m.valid_korean_headline('주가 조작 파문이 글로벌 주가지수에 영향',source))
        self.assertEqual(m.translation_input(source),'stock price manipulation scandal could affect global indexes')
        for text in ['Workers are fixing stock inventory records','A factory uses stock fixing machinery','The market for stock fixing clamps is expanding','Fixing a broken stock-market display']:
            self.assertEqual(m.translation_input(text),text)
        self.assertTrue(m.valid_korean_headline('재고 고정 장비','Stock fixing machinery'))

    def test_company_current_version_cache_rechecks_own_passage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'news').mkdir()
            a={'id':'context:one','title':'AI stock sell-off deepens','summary':'','impact':{'status':'unclear'},'publishedAt':'2026-10-15T01:00:00Z'}
            passage=m.short_passage(a)
            a['ko']={'version':m.VERSION,'sourceHash':m.source_hash(a),'sourceText':passage,'summary':'AI 주식 매출이 심화됐다.'}
            path=root/'news/latest.json';path.write_text(json.dumps({'issuers':{'1':{'articles':[a]}},'generatedAt':'2026-10-15T02:00:00Z'}))
            key=m.hashlib.sha256((m.VERSION+'\n'+passage).encode()).hexdigest()
            cache=root/'research/source-cache/news-ko/translations.json';cache.parent.mkdir(parents=True)
            cache.write_text(json.dumps({key:a['ko']['summary']}))
            calls=[]
            def translate(texts): calls.extend(texts); return ['AI 주식 매도세가 심화됐다.']*len(texts)
            first=m.translate_snapshot(root,translate)
            self.assertEqual(calls,[passage])
            row=first['issuers']['1']['articles'][0]
            self.assertEqual(row['ko']['status'],'ready');self.assertEqual(row['publishedAt'],a['publishedAt'])
            m.translate_snapshot(root,translate);self.assertEqual(calls,[passage])
            cache.write_text(json.dumps({key:'AI 주식 매출이 심화됐다.'}))
            m.translate_snapshot(root,translate);self.assertEqual(calls,[passage], 'Good source-bound article replaces an invalid cache')
            latest=json.loads(path.read_text()); latest['issuers']['1']['articles'][0]['title']='AI stock sell-off eases';path.write_text(json.dumps(latest))
            m.translate_snapshot(root,translate);self.assertEqual(calls[-1],'AI stock sell-off eases')


if __name__ == '__main__': unittest.main()
