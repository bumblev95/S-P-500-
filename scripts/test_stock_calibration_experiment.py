import copy
import unittest
import numpy as np
import run_stock_calibration_experiment as e

class CalibrationProtocol(unittest.TestCase):
    def rows(self):
        rows=[]
        for year in range(2010,2018):
            for j in range(80):
                p=.05+.9*j/79
                rows.append(dict(symbol=f'S{j}',origin=f'{year}-01-01',targetDate=f'{year}-12-30',
                    y=.9 if j>40 else 1.1,independentReturnScores={'raw':[p,0,1-p],'down':p,'calibrated':True}))
        return rows

    def test_future_and_same_day_outcomes_do_not_change_predictions(self):
        rows=self.rows();origin='2016-01-01'
        p,fit=e.predict_origin(rows,origin)
        changed=copy.deepcopy(rows)
        for r in changed:
            if r['targetDate']>=origin:r['y']=1e8
        q,other=e.predict_origin(changed,origin)
        self.assertEqual(fit,other)
        for a,b in zip(p,q):
            for name in (*e.METHODS,'prior'):self.assertEqual(a[name],b[name])
        self.assertEqual(fit,e.predict_origin([r for r in rows if r['origin']<=origin],origin)[1])

    def test_sigmoid_preserves_raw_order_even_on_reversed_labels(self):
        rows=self.rows()
        for r in rows:r['y']=1.1 if r['y']<1 else .9
        coefficients,status=e.fit_monotone(rows)
        self.assertTrue(status['fitted'])
        self.assertGreater(coefficients[0],0)
        out=[e.apply_monotone(p,coefficients) for p in np.linspace(.01,.99,99)]
        self.assertTrue(all(a<b for a,b in zip(out,out[1:])))

    def test_insufficient_dates_are_unavailable(self):
        p,s=e.fit_monotone(self.rows()[:160])
        self.assertIsNone(p);self.assertFalse(s['fitted'])

    def test_equal_date_metric_is_not_pooled_metric(self):
        rows=[dict(origin='2020',symbol='A',y=.9,raw=.9)]
        rows += [dict(origin='2021',symbol=str(i),y=1.1,raw=.9) for i in range(100)]
        m=e.metric(rows,'raw')
        self.assertAlmostEqual(m['dateMeanBrier'],.41)

if __name__=='__main__':unittest.main()
