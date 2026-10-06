import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from collect_simulation_data import valid,merge,collect,COINS,HL

class SimulationDataTests(unittest.TestCase):
    def test_impossible_candles_are_rejected(self):
        r=dict(t=0,end=899999,open=100,high=101,low=99,close=100,volume=0)
        self.assertTrue(valid(r))
        for patch in [dict(close=102),dict(low=0),dict(volume=-1),dict(open=float('nan')),dict(end=0)]:
            self.assertFalse(valid(dict(r,**patch)))
    def test_old_bars_are_frozen_and_material_revisions_flagged(self):
        r=dict(t=0,end=899999,open=100,high=101,low=99,close=100,volume=100)
        revised=dict(r,open=50,high=51,low=49,close=50)
        result,changes=merge([r],[revised]);self.assertEqual(result,[r]);self.assertEqual(changes,[0])
        result,changes=merge([r],[dict(r,t=900000,end=1799999)]);self.assertEqual(len(result),2);self.assertEqual(changes,[])

    def test_crypto_only_refresh_preserves_public_file_and_filters_unfinished_inputs(self):
        cutoff=datetime(2026,10,6,16,16,tzinfo=timezone.utc);ms=int(cutoff.timestamp()*1000)
        end=1791302399999
        prior=dict(t=end-899999,end=end,open=100,high=101,low=99,close=100,volume=100)
        funding=[dict(time=end-3600000,rate=.0001)]
        old=dict(schemaVersion=1,generatedAt='2026-10-06T16:14:55.710200+00:00',stocks={'SPY':{'rows':[{'date':'2026-10-05'}]}},
                 errors=[],crypto={s:dict(frames={'15m':[prior],'1h':[]},funding=funding,errors=[],revisions=[]) for s in COINS})
        requests=[]
        def fetch(url,body=None):
            self.assertEqual(url,HL);requests.append(body)
            if body['type']=='fundingHistory':
                return [dict(coin=body['coin'],time=ms-1,fundingRate='.0002'),dict(coin=body['coin'],time=ms,fundingRate='.01')]
            req=body['req'];self.assertEqual(req['endTime'],ms)
            step=900000 if req['interval']=='15m' else 3600000
            t=ms//step*step-step
            return [dict(s=req['coin'],i=req['interval'],t=t+shift,T=t+shift+step-1,o='100',h='101',l='99',c='100',v='100') for shift in (0,step)]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'simulation/market.json';source.parent.mkdir();source.write_text(json.dumps(old));before=source.read_bytes()
            output=root/'private/market.json'
            with patch('collect_simulation_data.fetch',side_effect=fetch):result=collect(root,now=cutoff,crypto_only=True,output=output)
            self.assertEqual(source.read_bytes(),before);self.assertEqual(result['stocks'],old['stocks']);self.assertEqual(result['errors'],[])
            self.assertEqual(json.loads(output.read_text()),result);self.assertEqual(len(requests),9)
            for s in COINS:
                self.assertEqual(result['crypto'][s]['frames']['15m'][0],prior)
                self.assertEqual(result['crypto'][s]['frames']['15m'][-1]['end'],1791303299999)
                self.assertEqual(result['crypto'][s]['funding'][0],funding[0])
                self.assertTrue(all(r['end']<ms for rows in result['crypto'][s]['frames'].values() for r in rows))
                self.assertTrue(all(r['time']<ms for r in result['crypto'][s]['funding']))

    def test_public_collector_samples_crypto_clock_after_stock_collection(self):
        before=datetime(2026,10,6,16,14,55,tzinfo=timezone.utc)
        after=datetime(2026,10,6,16,15,5,tzinfo=timezone.utc);requests=[]
        def fetch(url,body=None):
            self.assertEqual(url,HL);requests.append(body);return []
        with tempfile.TemporaryDirectory() as directory:
            with patch('collect_simulation_data.datetime',wraps=datetime) as clock,patch('collect_simulation_data.STOCKS',{}),patch('collect_simulation_data.fetch',side_effect=fetch):
                clock.now.side_effect=[before,after];result=collect(Path(directory))
            self.assertEqual(result['generatedAt'],after.isoformat())
            for request in requests:
                self.assertEqual(request.get('req',request)['endTime'],int(after.timestamp()*1000))

if __name__=='__main__':unittest.main()
