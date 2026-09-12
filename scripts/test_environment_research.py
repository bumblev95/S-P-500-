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
                for r in v['outcomes']:self.assertLess(r['contextThrough'],r['origin'])
                c=v['comparison']
                if c['status']=='research':self.assertLess(c['selectionTargetThrough'],c['evaluationStart'])
if __name__=='__main__':unittest.main()
