"""Verify byte-identical offline replay; no downloads or production writes."""
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
reference=json.loads((HERE/'output/verification.json').read_text())
for name,expected in reference['outputHashes'].items():
    for folder in ('output','replay'):
        got=hashlib.sha256((HERE/folder/name).read_bytes()).hexdigest()
        if got!=expected:raise SystemExit('Replay mismatch: '+folder+'/'+name)
print('PASS: results.json, predictions.json.gz, metrics.csv replay byte-for-byte')
