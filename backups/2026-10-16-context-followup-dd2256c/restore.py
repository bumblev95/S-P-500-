"""Verify the backup and restore only unchanged repair files. No files are deleted."""
import argparse, hashlib, json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
base=Path(__file__).resolve().parent;repo=args.repo.resolve();manifest=json.loads((base/'manifest.json').read_text());changes=[]
for name,hashes in manifest['restore'].items():
    old=(base/'original'/name).read_bytes();target=repo/name
    assert hashlib.sha256(old).hexdigest()==hashes['before'], 'Backup checksum mismatch: '+name
    digest=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    assert digest in (hashes['before'],hashes['after']), 'Later modification or missing file; nothing restored: '+name
    if digest!=hashes['before']: changes.append((target,old));print('Restore:',name)
if args.apply:
    for target,data in changes: target.write_bytes(data)
    print('Restored',len(changes),'existing files. No files deleted. Review diff and test before a rollback PR.')
else: print('Dry run only. Use --apply after reviewing these exact files.')
