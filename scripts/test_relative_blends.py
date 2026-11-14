"""Chronology, issuer uniqueness and leakage checks for relative-strength research."""
import copy,json,unittest
import numpy as np
from collect_relative_inputs import own_features,residual_features
from research_relative_blends import choose_weight,matrix,matured,validate,weighted_score

class RelativeTests(unittest.TestCase):
    def history(self):
        from datetime import date,timedelta
        return [((date(2018,1,1)+timedelta(days=i)).isoformat(),100*np.exp(.0002*i+.01*np.sin(i))) for i in range(300)]

    def test_raw_features_do_not_read_origin_or_future_prices(self):
        series=self.history();origin=series[270][0]
        poisoned=series[:270]+[(d,p*1000) for d,p in series[270:]]
        self.assertEqual(own_features(series,origin),own_features(poisoned,origin))
        self.assertEqual(residual_features(series,series,[],origin),residual_features(poisoned,poisoned,[],origin))
        self.assertLess(own_features(series,origin)['through'],origin)

    def test_residual_identical_market_has_beta_one_and_zero_residual(self):
        series=self.history();r=residual_features(series,series,[], '2020-01-01')
        self.assertFalse(r['sectorAvailable']);self.assertAlmostEqual(r['values'][0],1.)
        np.testing.assert_allclose(r['values'][1:],0.,atol=1e-12)

    def test_feature_matrix_cannot_read_future_targets(self):
        row=dict(symbol='TEST',origin='2020-01-01',priceOnly=1.1,environment=1.2,balanced=1.1,independentReturn=1.1,secDynamics=1.1,y=.1)
        feature={'TEST|2020-01-01':dict(usable=True,absolute=[0.]*14,relative=[0.]*11)}
        before=matrix([row],feature,True);row.update(y=100.,targetDate='2099-01-01')
        np.testing.assert_array_equal(before,matrix([row],feature,True))

    def test_stack_only_uses_strictly_mature_oos_labels(self):
        history=[]
        for year in [2016,2017,2018]:
            for y in [.8,1.2]:
                history.append(dict(origin=f'{year}-01-01',targetDate=f'{year}-07-01',y=y,inputUsable=True,maturedBounds=[.5,2.],
                    methods=dict(priceOnly=dict(value=1.),relative_expert=dict(value=y))))
        expected=choose_weight(history,'2020-01-01')
        poison=copy.deepcopy(history[0]);poison.update(origin='2019-01-01',targetDate='2020-01-01',y=100.)
        self.assertEqual(expected,choose_weight(history+[poison],'2020-01-01'))
        self.assertEqual(expected['weight'],1.)
        self.assertLess(expected['targetThrough'],'2020-01-01')

    def test_insufficient_stack_keeps_default_and_no_row_abstention(self):
        self.assertEqual(choose_weight([],'2020-01-01')['weight'],0.)
        self.assertEqual(choose_weight([],'2020-01-01')['status'],'fallback_priceOnly')
        self.assertEqual(matured([dict(origin='2019-01-01',targetDate='2020-01-01')],'2020-01-01'),[])

    def test_date_weighting_does_not_treat_more_tickers_as_more_market_dates(self):
        rows=[]
        for day,n,y,p in [('2020-01-01',100,1.2,1.2),('2021-01-01',1,.8,1.2)]:
            rows += [dict(origin=day,y=y,methods=dict(x=dict(value=p,direction=1))) for _ in range(n)]
        m=weighted_score(rows,'x')
        self.assertAlmostEqual(m['directionAccuracy'],.5)
        self.assertAlmostEqual(m['pooledAllRows']['directionAccuracy'],100/101)
        self.assertEqual(m['downRecall'],0.)

    def test_duplicate_issuer_and_overlap_are_rejected(self):
        row=dict(symbol='A',origin='2020-01-01',targetDate='2020-06-01',y=1.,priceOnly=1.,environment=1.,balanced=1.,independentReturn=1.,secDynamics=1.,
            independentReturnScores={'raw':[.3,.4,.3]},secDynamicsScores={'raw':[.3,.4,.3]})
        source=dict(generatedAt='2022-01-01',stocks={'126':dict(folds=[],outcomes=[row,copy.deepcopy(row)])})
        protocol={'horizons':[126],'sourceHash':'x'};snapshot={'sourceHash':'x','features':{}};universe={'members':{'A':{'cik':1}}}
        with self.assertRaisesRegex(ValueError,'CIK'):validate(source,snapshot,protocol,universe)
        second=copy.deepcopy(row);second.update(origin='2020-05-01',targetDate='2020-12-01')
        source['stocks']['126']['outcomes']=[row,second]
        with self.assertRaisesRegex(ValueError,'Overlapping'):validate(source,snapshot,protocol,universe)

if __name__=='__main__':unittest.main()
