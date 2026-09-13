import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
import pandas as pd
from build_learned_forecasts import feature_frame,examples,fit_at,metrics,qualifies,FEATURES

class LearnedTests(unittest.TestCase):
    def test_features_do_not_see_future(self):
        dates=pd.bdate_range('2016-01-01',periods=800).strftime('%Y-%m-%d')
        rows=[dict(date=d,close=100+np.sin(i/13)*3+i*.1,volume=1000+i) for i,d in enumerate(dates)]
        full=feature_frame(rows)
        before=feature_frame(rows[:600])
        pd.testing.assert_frame_equal(full.loc[before.index],before)

    def test_label_horizon_and_purge(self):
        dates=pd.bdate_range('2016-01-01',periods=1900).strftime('%Y-%m-%d').tolist()
        frames={}
        for n in range(60):
            f=pd.DataFrame({k:np.linspace(.01,.1,len(dates)) for k in FEATURES},index=dates)
            f['close']=100*np.exp(np.arange(len(dates))*.0001)
            frames[str(n)]=f
        data=examples(frames,126)
        row=data.iloc[0]
        self.assertEqual(row.targetDate,dates[126]);self.assertAlmostEqual(row.y,.0126)
        trained=fit_at(data,dates,dates[1800],126)
        self.assertIsNotNone(trained)
        meta=trained[3]
        self.assertLess(meta['trainTargetThrough'],meta['trainCutoff'])
        self.assertLess(meta['calibrationTargetThrough'],meta['origin'])

    def test_no_false_promotion(self):
        self.assertFalse(qualifies(metrics([])))
        base=dict(dates=6,mae=.2,noChangeMae=.1,trendMae=.1,directionAccuracy=.8,alwaysUpAccuracy=.6,rangeCoverage=.8,actualDownCount=10,downRecall=0.)
        self.assertFalse(qualifies(base))
        self.assertTrue(qualifies(dict(base,mae=.05)))
        self.assertFalse(qualifies(dict(base,mae=.05,dates=3)))

if __name__=='__main__':unittest.main()
