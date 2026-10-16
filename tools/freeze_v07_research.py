"""Preserve registered research inputs before refreshing the parent datasets."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analyzer_support import atomic_json, digest
from tools.export_source import DATA


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    parent, out = args.parent.resolve(), args.out.resolve()
    if out.exists():
        raise ValueError('Choose a fresh snapshot directory')
    protocol = json.loads(args.protocol.read_text())
    sources = json.loads((ROOT/'source_manifest.json').read_text())
    paths = set(DATA) | set(sources['allowlist']) | set(protocol['code'])
    paths |= {row['path'] for row in protocol['datasets'].values()}
    expected = dict(protocol['code'])
    expected.update({row['path']: row['sha256'] for row in protocol['datasets'].values()})
    for rel, sha in expected.items():
        if digest(parent/rel) != sha:
            raise ValueError('Registered input changed: '+rel)
    inventory = []
    for rel in sorted(paths):
        target = out/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(parent/rel, target)
        sha = digest(parent/rel)
        if digest(target) != sha:
            raise ValueError('Copy mismatch: '+rel)
        inventory.append(dict(path=rel, sha256=sha))
    atomic_json(out/'FROZEN_INPUTS.json', dict(protocol_signature=protocol['signature'], files=inventory))
    print('Preserved and verified', len(inventory), 'research files')


if __name__ == '__main__':
    main()
