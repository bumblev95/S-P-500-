import copy
import unittest
from datetime import date,timedelta
from build_adaptive_research import fit,predict,matured,band,compare,weights,stats,normalize

def fixture(n=14):
    rows=[]
    for i in range(n):
        origin=date(2020,1,1)+timedelta(days=40*i)
        for j in range(20):
            rows.append(dict(symbol=str(j),origin=origin.isoformat(),targetDate=(origin+timedelta(days=20)).isoformat(),
                             y=.08,original=-.04,noChange=0.,trend=.01,ma200=.1,vol84=.2,
                             biasCorrected=.02,regimeBlend=.03))
    return rows

class AdaptiveTests(unittest.TestCase):
    def test_future_outcomes_cannot_change_correction(self):
        rows=fixture();origin=rows[120]['origin'];a=fit(rows,origin)
        changed=copy.deepcopy(rows)
        for r in changed:
            if r['targetDate']>=origin:r['y']=100
        self.assertEqual(a,fit(changed,origin))
        self.assertLess(a['targetThrough'],origin)
        self.assertEqual(predict(rows[120],a),predict(rows[120],fit(changed,origin)))

    def test_entire_date_must_be_mature_and_windows_disjoint(self):
        rows=fixture();origin=rows[120]['origin'];d=rows[100]['origin']
        rows[100]['targetDate']=origin
        self.assertNotIn(d,{r['origin'] for r in matured(rows,origin)})
        rows=fixture();rows[0]['targetDate']=rows[60]['origin']
        dates=sorted({r['origin'] for r in matured(rows,'2030-01-01')})
        self.assertNotIn(rows[20]['origin'],dates)

    def test_same_date_more_stocks_do_not_create_evidence(self):
        rows=fixture(3)*10
        self.assertIsNone(fit(rows,'2030-01-01'))
        rows=fixture(4);w=weights(rows)
        self.assertAlmostEqual(w[:20].sum(),1)
        extra=[dict(rows[0],symbol='extra'+str(i)) for i in range(100)]
        self.assertAlmostEqual(stats(rows,'original')['mae'],stats(rows+extra,'original')['mae'])

    def test_forecast_blend_is_convex_and_bias_shrunk(self):
        p=fit(fixture(),'2030-01-01')
        self.assertAlmostEqual(sum(p['weights'].values()),1)
        self.assertTrue(all(1/6<=v<=2/3 for v in p['weights'].values()))
        self.assertAlmostEqual(p['bias'],.06)

    def test_band_uses_only_completed_adapter_predictions(self):
        rows=fixture();origin=rows[80]['origin'];b=band(rows,origin,'biasCorrected')
        self.assertLess(b['targetThrough'],origin)
        changed=copy.deepcopy(rows)
        for r in changed:
            if r['targetDate']>=origin:r['biasCorrected']=-100
        self.assertEqual(b,band(changed,origin,'biasCorrected'))
        self.assertIsNone(band(fixture(2),'2030-01-01','biasCorrected'))

    def test_later_results_never_select_candidate(self):
        rows=fixture();first=compare(rows);changed=copy.deepcopy(rows)
        for r in changed:
            if r['origin']>=first['evaluationStart']:
                r['regimeBlend']=-1;r['biasCorrected']=r['y']
        second=compare(changed)
        self.assertEqual(first['chosen'],second['chosen'])
        self.assertLess(first['selectionTargetThrough'],first['evaluationStart'])
        self.assertFalse(second['passed'])
        self.assertFalse(compare(fixture(3))['passed'])

    def test_source_causality_and_duplicate_rejection(self):
        r=fixture(1)[0];r['pred']=r['original']
        source=dict(outcomes=[r],folds=[dict(origin=r['origin'],trainTargetThrough='2019-01-01',calibrationTargetThrough='2019-12-01')])
        self.assertEqual(len(normalize(source)),1)
        source['outcomes'].append(r)
        with self.assertRaises(ValueError):normalize(source)
        source['outcomes']=[r];source['folds'][0]['calibrationTargetThrough']=r['origin']
        with self.assertRaises(ValueError):normalize(source)

if __name__=='__main__':unittest.main()
