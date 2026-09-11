import unittest
from datetime import datetime,timezone,timedelta
from build_crypto import candles,indicators,forecast,assess,observed_change,fresh
class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,9,11,22,tzinfo=timezone.utc);s=self.now.isoformat()
        self.rows=[dict(date=(self.now-timedelta(days=100-i)).date().isoformat(),open=100+i*.2,close=100+i*.2,high=104+i*.2,low=96+i*.2,volume=1000) for i in range(100)]
        self.e=dict(history=self.rows,macroState='stable',spot=dict(price=120,at=s,volume24h=1e9,marketCap=1e10,fdv=1e10),perp=dict(mark=120,at=s,volume24h=1e9,openInterestUSD=1e8,fundingHourly=0,premium=0),supply=dict(circulating=100.0000001,total=100),book=dict(at=s,spread=.0001))
    def test_candles(self):
        r=dict(t=0,T=999,o='10',h='12',l='9',c='11',v='5')
        self.assertEqual(len(candles([r,dict(r,t=2000,T=2999)],2000)),1)
        self.assertEqual(candles([dict(r,c='13')],2000),[])
    def test_forecast(self):
        ind=indicators(self.rows)
        for h in (30,120,365):
            f=forecast(120,ind,h);self.assertLessEqual(f['bear'],f['base']);self.assertLessEqual(f['base'],f['bull'])
    def test_missing_and_stale(self):
        ind=indicators(self.rows);a=assess(self.e,ind,self.now);self.assertIsNotNone(a['components']['supply'])
        self.e['perp']['fundingHourly']=None;a=assess(self.e,ind,self.now)
        self.assertEqual(a['perpAction'],'관망');self.assertIsNone(a['longScore'])
        self.e['spot']['at']='2026-09-01T00:00:00+00:00';self.assertEqual(assess(self.e,ind,self.now)['spotAction'],'관망')
        self.e['macroState']='risk';self.assertEqual(assess(self.e,ind,self.now)['perpAction'],'관망')
    def test_missing_liquidity_is_null(self):
        self.e['spot']['volume24h']=None
        self.assertIsNone(assess(self.e,indicators(self.rows),self.now)['components']['liquidity'])
    def test_missing_history(self):
        self.e['history']=[];a=assess(self.e,None,self.now);self.assertIsNone(a['indicators']);self.assertEqual(a['perpAction'],'관망')
    def test_observations(self):
        self.assertIsNone(observed_change([],'BTC','circulating',self.now.isoformat()))
        r=dict(at=(self.now-timedelta(hours=24)).isoformat(),symbol='BTC',circulating=100)
        self.assertEqual(observed_change([r],'BTC','circulating',self.now.isoformat()),100)
        self.assertFalse(fresh((self.now+timedelta(hours=1)).isoformat(),self.now))
if __name__=='__main__':unittest.main()
