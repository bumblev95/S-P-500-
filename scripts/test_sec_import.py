import json, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import build_research_inputs as source
from import_sec_companyfacts import ingest,validated

def payload(cik=1045810):
    rows=[dict(start=f'{y}-01-01',end=f'{y}-12-31',filed=f'{y+1}-02-01',form='10-K',val=v,accn=str(y)) for y,v in ((2021,100),(2022,120))]
    return dict(cik=cik,facts={'us-gaap':{'Revenues':{'units':{'USD':rows}}}})

class SecImport(unittest.TestCase):
    def test_json_and_zip_give_same_dated_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'nvda.json';p.write_text(json.dumps(payload()))
            a=ingest([p],root);z=root/'companyfacts.zip'
            with zipfile.ZipFile(z,'w') as archive:archive.writestr('CIK0001045810.json',p.read_bytes())
            b=ingest([z],root)
            self.assertEqual(a['stocks']['NVDA']['rows'],b['stocks']['NVDA']['rows'])
            self.assertAlmostEqual(source.stock_before(b['stocks']['NVDA']['rows'],'2023-02-02')[0][0],.2)
            self.assertIsNone(b['stocks']['NVDA']['retrievedAt'])
    def test_wrong_issuer_rejected(self):
        with self.assertRaises(ValueError):validated(json.dumps(payload()),320193)
    def test_unconfigured_request_stops_before_network(self):
        with patch.dict(source.os.environ,{'SEC_USER_AGENT':''}),patch.object(source,'urlopen') as network:
            with self.assertRaises(ValueError):source.request('https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json')
            network.assert_not_called()
    def test_contact_not_sent_to_crypto(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'[]'
        with patch.dict(source.os.environ,{'SEC_USER_AGENT':'ForecastResearch contact@example.org'}),patch.object(source,'urlopen',return_value=Response()) as network:
            source.request(source.HL,{'type':'metaAndAssetCtxs'})
            self.assertNotIn('contact@example.org',network.call_args.args[0].get_header('User-agent'))

if __name__=='__main__':unittest.main()
