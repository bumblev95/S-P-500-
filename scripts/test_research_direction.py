import copy
import unittest
import numpy as np
from research_direction import financial_changes, calibrate_direction
import build_environment_research as m


class DirectionExperiments(unittest.TestCase):
    def test_changes_ignore_future_and_same_period_restatements(self):
        prior=dict(periodEnd='2022-12-31',availableDate='2023-03-01',revenueGrowth=.1,netMargin=.1,cashflowMargin=.2,liabilitiesToAssets=.5)
        current=dict(periodEnd='2023-12-31',availableDate='2024-03-01',revenueGrowth=.3,netMargin=.2,cashflowMargin=.25,liabilitiesToAssets=.4)
        restated={**current,'availableDate':'2024-04-01','revenueGrowth':.35}
        future={**current,'availableDate':'2024-06-01','revenueGrowth':999.}
        a,through=financial_changes([prior,current,restated],[],'2024-05-01')
        b,_=financial_changes([future,restated,prior,current],[],'2024-05-01')
        np.testing.assert_equal(a,b)
        self.assertAlmostEqual(a[0],.25)
        self.assertAlmostEqual(a[4],.05)
        self.assertEqual(through,'2024-04-01')
        self.assertTrue(all(np.isnan(v) for v in financial_changes([prior,current],[],'2026-01-01')[0]))

    def test_direction_is_separate_from_price(self):
        rows=[dict(origin='2020-01-01',y=.9,independentReturn=1.1,independentReturnDirection=-1)]
        s=m.score(rows,'independentReturn')
        self.assertEqual(s['directionAccuracy'],1.)
        self.assertEqual(s['returnDirectionAccuracy'],0.)
        self.assertEqual(s['downPrecision'],1.)
        self.assertGreater(s['mape'],.2)

    def test_unforced_prediction_is_exact_regressor_output(self):
        rows=[dict(y=y,w=[j%7,regime],regime='상승·보통변동') for regime,y in enumerate((.9,1.,1.1)) for j in range(90)]
        fitted=m.fit_horizon(rows,126)
        values,details=fitted.predict_independent(rows,[],'independentReturn','2024-01-01')
        np.testing.assert_allclose(values,np.exp(fitted.return_model.predict(fitted.matrix(rows))))
        self.assertFalse(details[0]['calibrated'])

    def test_calibration_uses_only_realized_oos_raw_scores(self):
        prior=[]
        for year in (2020,2021,2022):
            for label,y in enumerate((.9,1.,1.1)):
                for _ in range(25):
                    raw=[.1,.1,.1];raw[label]=.8
                    prior.append(dict(origin=f'{year}-01-01',targetDate=f'{year}-12-01',y=y,secDynamicsScores={'raw':raw}))
        raw=[[.1,.1,.8]]
        a=calibrate_direction(raw,prior,'secDynamics','2023-01-01')
        contaminated=prior+[dict(origin='2022-12-01',targetDate='2023-01-01',y=.1,secDynamicsScores={'raw':[.1,.1,.8]})]*100
        self.assertEqual(a,calibrate_direction(raw,contaminated,'secDynamics','2023-01-01'))
        self.assertTrue(a[0]['calibrated'])
        self.assertLess(a[0]['targetThrough'],'2023-01-01')
        self.assertEqual(a[0]['chosen'],1)

    def test_selection_prioritizes_direction_and_cannot_see_later(self):
        rows=[]
        for year in range(2000,2016):
            for j in range(40):
                y=.9 if j%2 else 1.1
                rows.append(dict(origin=f'{year}-01-01',targetDate=f'{year}-12-01',y=y,noChange=1.,priceOnly=1.05,environment=y,ensemble=1.05,balanced=1.05,
                    independentReturn=y*1.01,independentReturnDirection=m.direction_label(y),
                    secDynamics=y,secDynamicsDirection=1))
        a=m.compare(rows)
        self.assertFalse(a['selectionChecks']['secDynamics']['direction'])
        # environment has good signed return and may win; the misleading classifier cannot.
        self.assertNotEqual(a['chosen'],'secDynamics')
        changed=copy.deepcopy(rows)
        for r in changed:
            if r['origin']>=a['evaluationStart']:r.update(y=.1,environment=99.)
        b=m.compare(changed)
        self.assertEqual(a['chosen'],b['chosen'])
        self.assertEqual(a['selectionChecks'],b['selectionChecks'])
        for r in rows:
            r.update(environment=1.05,independentReturnDirection=1)
        c=m.compare(rows)
        self.assertFalse(c['selectionEligible'])
        self.assertFalse(c['passed'])

    def test_fitted_pipeline_preserves_matched_samples_and_calibration_dates(self):
        from datetime import date,timedelta
        from unittest.mock import patch
        import contextlib,io,json
        def records(hist,context,h,asset_class,inputs):
            rows=[]
            for month in range(300):
                origin=date(2000+month//12,month%12+1,1)
                for j in range(12):
                    y=(.85,1.,1.15)[(j+month)%3]
                    x=[j/12.,month%12/12.]
                    rows.append(dict(symbol=f'S{j}',origin=str(origin),targetDate=str(origin+timedelta(days=round(h*365/252))),y=y,
                        anchor=100.,x=x,z=x,w=x+[.1]*8,v=x+[1.]*8,d=x+[.1]*15,inputCount=8,dynamicCount=7,
                        inputThrough=str(origin-timedelta(days=2)),contextThrough=str(origin-timedelta(days=1)),regime='상승·보통변동'))
            return rows,{r['symbol']:r for r in rows[-12:]}
        with patch.object(m,'records',side_effect=records),contextlib.redirect_stdout(io.StringIO()):
            out=m.run_class({}, {}, 'stocks')
        json.dumps(out,allow_nan=False)
        for v in out.values():
            counts={metric['n'] for metric in v['experiments']['evaluation'].values()}
            self.assertEqual(len(counts),1)
            for row in v['outcomes']:
                for name in ('independentReturn','secDynamics'):
                    through=row[name+'Scores']['targetThrough']
                    if through:self.assertLess(through,row['origin'])
            for row in v['predictions'].values():
                self.assertGreater(row['secDynamics'],0.)
                self.assertEqual(len(row['dynamicValues']),7)


if __name__=='__main__':unittest.main()
