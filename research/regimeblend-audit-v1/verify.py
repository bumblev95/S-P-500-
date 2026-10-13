"""Verify preserved repository bytes and deterministic isolated audit outputs."""
import argparse
import json
from pathlib import Path
from run import HERE, ROOT, digest, read_sources


def verify_preserved(root=ROOT):
    preserved=json.loads((HERE/'preserved-files.json').read_text())
    for entry in preserved['files']:
        if digest((root/entry['path']).read_bytes()) != entry['sha256']:
            raise ValueError('Preserved baseline file changed: '+entry['path'])
    return len(preserved['files'])


def verify_output(output=HERE/'output'):
    verification=json.loads((output/'verification.json').read_text())
    for name,expected in verification['outputHashes'].items():
        if digest((output/name).read_bytes()) != expected:
            raise ValueError('Audit output hash mismatch: '+name)
    return verification['outputHashes']


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=HERE/'output')
    parser.add_argument('--compare',type=Path);args=parser.parse_args()
    read_sources();count=verify_preserved();hashes=verify_output(args.output)
    if args.compare:
        if hashes != verify_output(args.compare): raise ValueError('Replay outputs differ')
        if (args.output/'verification.json').read_bytes() != (args.compare/'verification.json').read_bytes():
            raise ValueError('Replay verification records differ')
    print('Verified frozen sources,',count,'preserved baseline files and isolated output hashes')
