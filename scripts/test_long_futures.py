import unittest
from train_long_futures import partition,stamp

class LongChronology(unittest.TestCase):
    def test_calendar_partitions_purge_outcomes(self):
        rows=[{'at':stamp(y)+d*86400000,'labelEnd':stamp(y)+d*86400000+8*3600000} for y in range(2020,2027) for d in range(0,365,5)]
        train,val,test=partition(rows,2025)
        self.assertLess(max(r['labelEnd'] for r in train),stamp(2024)-8*3600000)
        self.assertTrue(all(stamp(2024)<=r['at'] and r['labelEnd']<stamp(2025)-8*3600000 for r in val))
        self.assertTrue(all(stamp(2025)<=r['at'] and r['labelEnd']<stamp(2026) for r in test))

if __name__=='__main__':unittest.main()
