import unittest
from datetime import date,timedelta
import numpy as np
import analyze_top3_rankings as A

class RankingAnalysisTests(unittest.TestCase):
    def test_calendar_gaps_not_zero_filled(self):
        q=A.block_interval([.03]*65+[np.nan]*3+[.03]*65)
        self.assertAlmostEqual(q["meanDelta"],.03)
        for x in q["ci95"]:self.assertAlmostEqual(x,.03)
        self.assertEqual(q["validDates"],130)

    def test_pair_only_complete_top3_same_dates(self):
        def rows(day,n,value):
            return [{"date":day,**{k:value for k in A.METRICS}} for _ in range(n)]
        baseline=rows("2020-01-01",3,0)+rows("2020-01-02",3,0)
        candidate=rows("2020-01-01",3,.02)+rows("2020-01-02",2,1)
        q=A.paired(candidate,baseline,"excess",["2020-01-01","2020-01-02"])
        self.assertEqual(q["pairedDates"],1)
        self.assertAlmostEqual(q["delta"],.02)

    def test_daily_weighting_and_stress_cost_identity(self):
        def rows(day,n,value):
            return [{"date":day,**{k:value for k in A.METRICS},"benchmark":0.,"gross":.01} for _ in range(n)]
        q=A.aggregate(rows("2020-01-01",3,0)+rows("2020-01-02",1,1))
        self.assertEqual(q["dateBalancedNet"],.5)
        self.assertEqual(q["meanAdverse"],.5)
        r=rows("2020-01-01",1,0)[0]
        r["net"]=1.01*(1-.0005)**2/(1+.0005)**2-1
        stressed=A.cost_rows([r],2)[0]
        self.assertAlmostEqual(stressed["net"],1.01*(1-.001)**2/(1+.001)**2-1)
        self.assertAlmostEqual(stressed["avoidance"],-.01*(1-.001)**2)

if __name__=="__main__":unittest.main()
