import unittest
from datetime import date,timedelta
from score_live_forecasts import evaluate,summary

class LiveTests(unittest.TestCase):
    def setUp(self):
        self.history=[dict(date=(date(2026,1,1)+timedelta(days=i)).isoformat(),close=100+i) for i in range(30)]
        self.entry=dict(asOf='2026-01-01')
        self.record=dict(status='eligible',forecast=dict(horizon=21,anchor=100,base=120,bear=90,bull=130))
    def test_pending_is_not_zero_accuracy(self):
        r=evaluate(self.entry,self.record,'2026-01-01T23:30:00Z',self.history[:21])
        self.assertEqual(r['status'],'pending')
        self.assertIsNone(summary([r])['directionAccuracy'])
    def test_correct_horizon_and_baseline(self):
        r=evaluate(self.entry,self.record,'2026-01-01T23:30:00Z',self.history)
        self.assertEqual(r['targetDate'],'2026-01-22')
        self.assertAlmostEqual(r['error'],.01)
        self.assertAlmostEqual(r['baselineError'],.21)
        self.assertTrue(r['rangeHit'])
    def test_withheld_not_counted(self):
        self.record['status']='withheld'
        r=evaluate(self.entry,self.record,'2026-01-01T23:30:00Z',self.history)
        self.assertEqual(summary([r])['scored'],0)
        self.assertEqual(summary([r])['researchRecords'],1)
    def test_late_issue_split_missing_origin(self):
        self.assertEqual(evaluate(self.entry,self.record,'2026-01-22T23:30:00Z',self.history)['status'],'excluded')
        self.assertEqual(evaluate(self.entry,self.record,'2026-01-01T23:30:00Z',self.history[1:])['status'],'unavailable')
        self.history[0]['close']=50
        self.assertEqual(evaluate(self.entry,self.record,'2026-01-01T23:30:00Z',self.history)['status'],'excluded')

if __name__=='__main__':unittest.main()
