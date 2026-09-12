import unittest
from train_pattern_research import split_rows

class Chronology(unittest.TestCase):
    def test_common_time_split_and_purged_labels(self):
        rows=[dict(at=t*900000,labelEnd=(t+8)*900000) for t in range(200)]
        train,val,test,b=split_rows(rows)
        self.assertLess(max(r['labelEnd'] for r in train),b['validationStart']-b['embargoMs'])
        self.assertLess(max(r['labelEnd'] for r in val),b['testStart']-b['embargoMs'])
        self.assertGreaterEqual(min(r['at'] for r in test),b['testStart'])
    def test_previous_test_is_not_recounted_as_new(self):
        rows=[dict(at=t*900000,labelEnd=(t+8)*900000) for t in range(300)]
        _,_,test,_=split_rows(rows,previous_end=270*900000)
        self.assertTrue(all(r['at']>270*900000 for r in test))

if __name__=='__main__':unittest.main()
