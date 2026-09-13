import unittest, copy
import numpy as np
import build_environment_research as m
class EnvironmentResearch(unittest.TestCase):
    def test_context_before_not_same_day_or_future(self):
        f=[0.]*10;f[1]=.1;f[4]=.2;f[8]=.3
        series={'dates':np.array(['2024-01-02','2024-01-03']), 'features':{'2024-01-02':f,'2024-01-03':[9.]*10}}
        self.assertEqual(m.context_before(series,'2024-01-03'),([.1,.2,.3],'2024-01-02'))
        self.assertIsNone(m.context_before(series,'2024-01-02'))
        self.assertIsNone(m.context_before(series,'2024-01-10'))
    def test_metric_actual_price_denominator(self):
        r=[dict(origin='2020-01-01',y=2.,environment=1.)]
        self.assertEqual(m.score(r,'environment')['mape'],.5)
        self.assertEqual(m.score(r,'environment')['alwaysUpAccuracy'],1.)
    def test_log_error_treats_reciprocal_misses_equally(self):
        rows=[dict(origin='2020-01-01',y=1.,balanced=2.),dict(origin='2020-01-02',y=1.,balanced=.5)]
        result=m.score(rows,'balanced')
        self.assertAlmostEqual(result['logBias'],0.)
        self.assertAlmostEqual(result['logMae'],np.log(2))
    def test_calibration_ignores_unrealized_outcomes(self):
        rows=[dict(origin=f'{year}-01-01',targetDate=f'{year}-12-31',y=1.,balanced=1.1) for year in (2020,2021,2022) for _ in range(10)]
        before=m.calibration(rows,'2023-01-01')
        rows.append(dict(origin='2023-01-01',targetDate='2023-12-31',y=999,balanced=.001))
        self.assertEqual(before,m.calibration(rows,'2023-01-01'))
        self.assertIsNone(m.calibration(rows,'2022-01-01'))
    def test_interval_score_penalizes_width_and_misses(self):
        def score(lo,hi,y=1.):return m.interval_score([dict(origin='2020-01-01',y=y,range=dict(low=lo,high=hi))])
        self.assertLess(score(.9,1.1)['logIntervalScore'],score(.1,10)['logIntervalScore'])
        self.assertEqual(score(.9,1.1,2.)['coverage'],0.)
    def test_stock_horizons_have_independent_profiles_and_down_model(self):
        self.assertEqual({m.HORIZON_PROFILES[h]['name'] for h in (126,252)},
                         {'medium-126d','long-252d'})
        self.assertEqual(m.HORIZON_PROFILES[126]['field'],'w')
        rows=[]
        for label,y,regime in ((-1,.9,'하락·보통변동'),(0,1.,'상승·보통변동'),(1,1.1,'상승·고변동')):
            for i in range(120):
                rows.append(dict(y=y,z=[i%7/10],w=[i%7/10,1.],regime=regime))
        fitted=m.fit_horizon(rows,126);prediction,probability=fitted.predict(rows)
        labels=[m.direction_label(v) for v in prediction]
        self.assertIn(-1,labels);self.assertIn(0,labels);self.assertIn(1,labels)
        self.assertEqual(set(probability[0]),{'down','flat','up','chosen'})
    def test_selection_cannot_see_later_outcomes(self):
        rows=[]
        for year in range(2000,2016):
            rows.append(dict(origin=f'{year}-01-01',targetDate=f'{year}-12-01',y=1.2,noChange=1.,priceOnly=1.1,environment=1.19,ensemble=1.15))
        a=m.compare(rows);changed=copy.deepcopy(rows)
        for r in changed:
            if r['origin']>=a['evaluationStart']:r['y']=.5;r['environment']=10.
        b=m.compare(changed)
        self.assertEqual(a['chosen'],b['chosen'])
        self.assertLess(a['selectionTargetThrough'],a['evaluationStart'])
        self.assertFalse(a['liveForecastChanged'])
    def test_own_features_ignore_later_prices(self):
        from datetime import date,timedelta
        r=[{'date':str(date(2020,1,1)+timedelta(days=i)),'close':100+i/10} for i in range(240)]
        a=m.features(r);r[-1]['close']=1e6;b=m.features(r)
        self.assertEqual(a[r[-2]['date']],b[r[-2]['date']])
    def test_quarterly_features_reach_model_without_future_release(self):
        from datetime import date,timedelta
        prices=[dict(date=str(date(2024,1,1)+timedelta(days=i)),close=100+i/10) for i in range(500)]
        f=m.features(prices);context={key:dict(features=f,dates=np.array(sorted(f))) for key in m.PROXIES}
        first=dict(availableDate='2024-07-01',periodEnd='2024-06-30',quarterRevenueGrowth=.2,quarterNetMargin=-.1,quarterEpsChange=-.5,nextQuarterRevenueGrowth=None)
        later={**first,'availableDate':'2024-08-15','quarterRevenueGrowth':999.}
        a,_=m.records({'NVDA':prices},context,126,'stocks',{'earnings':{'NVDA':[first]}})
        b,_=m.records({'NVDA':prices},context,126,'stocks',{'earnings':{'NVDA':[first,later]}})
        by={r['origin']:r for r in b}
        before=[r for r in a if r['origin']<'2024-08-15']
        self.assertTrue(before)
        for row in before:
            np.testing.assert_equal(row['w'],by[row['origin']]['w'])
            self.assertEqual(row['w'][-4],.2);self.assertEqual(row['w'][-3],-.1)
            self.assertEqual(row['v'][-4],1.);self.assertEqual(row['inputThrough'],'2024-07-01')
    def test_output_chronology(self):
        import json
        p=m.ROOT/'research/environment.json'
        if not p.exists():self.skipTest('Run after builder for artifact audit')
        d=json.loads(p.read_text())
        for cls in ('stocks','crypto'):
            for h,v in d[cls].items():
                end=''
                for f in v['folds']:
                    self.assertLess(f['trainTargetThrough'],f['origin']);self.assertGreater(f['origin'],end);end=f['targetThrough']
                for f in v['predictions'].values():
                    self.assertLess(f['trainTargetThrough'],f['asOf']);self.assertLess(f['contextThrough'],f['asOf'])
                    if f.get('range'):self.assertLess(f['range']['targetThrough'],f['asOf'])
                    if f.get('inputThrough'):self.assertLess(f['inputThrough'],f['asOf'])
                for r in v['outcomes']:self.assertLess(r['contextThrough'],r['origin'])
                for r in v['outcomes']:
                    if r.get('range'):self.assertLess(r['range']['targetThrough'],r['origin'])
                    if r.get('inputThrough'):self.assertLess(r['inputThrough'],r['origin'])
                    for name in m.EXPERIMENTS:
                        detail=r.get(name+'Scores')
                        if detail and detail['targetThrough']:self.assertLess(detail['targetThrough'],r['origin'])
                if v.get('experiments'):
                    self.assertEqual(len({metric['n'] for metric in v['experiments']['evaluation'].values()}),1)
                    if not v['comparison'].get('selectionEligible'):self.assertFalse(v['comparison']['passed'])
                c=v['comparison']
                if c['status']=='research':self.assertLess(c['selectionTargetThrough'],c['evaluationStart'])
if __name__=='__main__':unittest.main()
