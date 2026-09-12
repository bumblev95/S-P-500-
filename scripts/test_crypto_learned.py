import copy,json,math,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import numpy as np
import build_crypto_learned as m

def series(n=1600):
    day=datetime(2020,1,1)
    return [dict(date=(day+timedelta(days=i)).date().isoformat(),close=100*math.exp(.0002*i+.15*math.sin(i/25))) for i in range(n)]
class SpotLearningTests(unittest.TestCase):
    def test_no_future_data_in_features_or_mature_training_rows(self):
        rows=series();btc={r['date']:[0,0] for r in rows};x=m.features(rows,350,btc)
        modified=copy.deepcopy(rows)
        for r in modified[351:]:r['close']*=100
        self.assertEqual(x,m.features(modified,350,btc))
        a,_=m.make_records({'BTC':{'rows':rows}},120)
        b,_=m.make_records({'BTC':{'rows':modified}},120)
        cutoff=rows[350]['date']
        self.assertEqual([r for r in a if r['targetDate']<cutoff],[r for r in b if r['targetDate']<cutoff])
    def test_annual_target_requires_actual_full_year(self):
        records,_=m.make_records({'BTC':{'rows':series(365)}},365)
        self.assertEqual(records,[])
        records,_=m.make_records({'BTC':{'rows':series(900)}},365)
        for r in records:self.assertEqual((datetime.fromisoformat(r['targetDate'])-datetime.fromisoformat(r['date'])).days,365)
    def test_return_features_are_scale_invariant(self):
        rows=series();btc={r['date']:[0,0] for r in rows}
        np.testing.assert_allclose(m.features(rows,350,btc),m.features([dict(r,close=r['close']*50) for r in rows],350,btc),rtol=1e-10,atol=1e-10)
    def test_yahoo_asset_identity_and_incomplete_bar(self):
        raw={'chart':{'result':[{'meta':{'symbol':'BTC-USD','currency':'USD','instrumentType':'CRYPTOCURRENCY','shortName':'Bitcoin USD'},'timestamp':[1704067200,1704153600],'indicators':{'quote':[{'close':[100,105]}]}}]}}
        rows=m.yahoo_rows(raw,'BTC-USD','bitcoin','2024-01-02');self.assertEqual(len(rows),1)
        with self.assertRaises(ValueError):m.yahoo_rows(raw,'ETH-USD','ethereum','2024-01-02')
    def test_source_alignment_and_gaps(self):
        rows=series(65);self.assertTrue(m.aligned(rows,rows));self.assertTrue(m.continuous(rows))
        self.assertFalse(m.aligned([dict(r,close=r['close']*2) for r in rows],rows))
        self.assertFalse(m.continuous(rows[:30]+rows[31:]))
    def test_delayed_provider_keeps_verified_long_history(self):
        old=series(900);cg=series(901)[-365:]
        self.assertTrue(m.aligned(old,cg))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'crypto/research-history';folder.mkdir(parents=True)
            (folder/'BTC.json').write_text(json.dumps(dict(source='Yahoo Finance spot daily USD',checkedDate='2022-06-19',prices=old)))
            result,errors=m.histories(root,{'coins':{'BTC':{'spotHistory':cg}}},datetime(2022,6,20,tzinfo=timezone.utc),download=False)
            self.assertEqual(len(result['BTC']['rows']),900)
            self.assertEqual(result['BTC']['rows'][-1]['date'],old[-1]['date'])
            self.assertEqual(errors,[])
    def test_last_common_bitcoin_date_is_used_without_inventing_inputs(self):
        rows=series(901)
        _,latest=m.make_records({'BTC':{'rows':rows[:-1]},'SOL':{'rows':rows}},30)
        self.assertEqual(latest['SOL']['asOf'],rows[-2]['date'])
        self.assertEqual(latest['SOL']['anchor'],rows[-2]['close'])
    def test_error_frequency_is_empirical_and_not_a_new_probability(self):
        samples=[dict(date='2020-01-0'+str(i+1),error=e,noChange=.2,trendError=.3,direction=i%2) for i,e in enumerate([0,.1,.26,1])]
        result=m.summary(samples)
        self.assertEqual(result['n'],4)
        self.assertEqual(result['over10Rate'],.5)
        self.assertEqual(result['over25Rate'],.5)
        self.assertAlmostEqual(result['medianError'],.18)
        self.assertAlmostEqual(result['mape'],.34)
        self.assertEqual(result['directionAccuracy'],.5)
        self.assertIsNone(m.summary([])['over10Rate'])
    def test_validation_gates_need_real_own_coin_evidence(self):
        self.assertFalse(m.passes(m.summary([])))
        good=dict(dates=6,mape=.1,noChangeMape=.2,trendMape=.3,dateWinRate=.5)
        self.assertTrue(m.passes(good));self.assertFalse(m.passes(dict(good,dates=5)))
        self.assertFalse(m.passes(dict(good,mape=.195)))
    def test_actual_published_folds_have_mature_labels_and_nonoverlap(self):
        path=Path(__file__).resolve().parents[1]/'crypto/learned.json'
        if not path.exists():self.skipTest('First model build has not run')
        data=json.loads(path.read_text())
        for h,r in data['validation'].items():
            folds=r['folds']
            for f in folds:self.assertLess(f['trainTargetThrough'],f['origin'])
            for a,b in zip(folds,folds[1:]):self.assertGreaterEqual((datetime.fromisoformat(b['origin'])-datetime.fromisoformat(a['origin'])).days,int(h))
        for coin in data['coins'].values():
            for h,r in coin['predictions'].items():
                if r.get('trainedThrough'):self.assertLess(r['trainedThrough'],coin['asOf'])
                if r['status']=='eligible':self.assertTrue(m.passes(r['validation']));self.assertTrue(m.passes(data['validation'][h]))
if __name__=='__main__':unittest.main()
