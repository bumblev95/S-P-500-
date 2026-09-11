import unittest
import numpy as np
import pandas as pd
from build_learned_forecasts import feature_frame,diagnostics,metrics,qualifies,fit_at,FEATURES

class PatternTests(unittest.TestCase):
    def test_features_do_not_change_when_future_is_appended(self):
        dates=pd.bdate_range('2018-01-01',periods=600).strftime('%Y-%m-%d')
        rows=[dict(date=d,close=100*np.exp(.0002*i+.02*np.sin(i/13)),volume=1000+i%30) for i,d in enumerate(dates)]
        past=feature_frame(rows[:450]);full=feature_frame(rows)
        pd.testing.assert_frame_equal(past,full.loc[past.index])
        self.assertTrue(np.isfinite(full[['rsi14','macd','macdHistogram','trendSlope','volumeMomentum']]).all().all())
    def test_neutral_direction_and_diagnostics(self):
        rows=[dict(origin=d,y=np.log(1.01),pred=0.,trend=0.,low=-.1,high=.1,ma200=.1,vol84=.3,rsi14=.5) for d in ['2020-01-01','2021-01-01']]
        self.assertEqual(metrics(rows)['directionAccuracy'],1)
        self.assertEqual(diagnostics(rows)['regimes']['above200']['n'],2)
        self.assertFalse(qualifies(metrics(rows)))
    def test_purged_training_and_calibration(self):
        calendar=list(pd.bdate_range('2010-01-01',periods=1400).strftime('%Y-%m-%d'))
        rows=[]
        for i in range(1300):
            for symbol in range(65):
                rows.append(dict.fromkeys(FEATURES,.01)|dict(origin=calendar[i],targetDate=calendar[i+21],symbol=str(symbol),y=.02))
        fitted=fit_at(pd.DataFrame(rows),calendar,calendar[1200],21)
        self.assertIsNotNone(fitted)
        meta=fitted[3]
        self.assertLess(meta['trainTargetThrough'],meta['trainCutoff'])
        self.assertLess(meta['calibrationTargetThrough'],meta['origin'])

if __name__=='__main__':unittest.main()
