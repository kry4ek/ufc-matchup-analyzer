"""Verify release archive inventories, content hashes, and CRCs against this tree."""
from pathlib import Path
import argparse, json, sys, zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import digest, manifest
from tools.package_release import public_files

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,default=ROOT.parent/'release-assets');args=parser.parse_args()
    data={x['path']:x['sha256'] for x in manifest()['files']}
    public=set(public_files())
    listing=json.loads((args.directory/'archive_manifest.json').read_text(encoding='utf-8'))
    count=0
    for item in listing['archives']:
        path=args.directory/item['file']
        if digest(path)!=item['sha256']:raise ValueError('Archive checksum mismatch: '+path.name)
        if path.stat().st_size!=item['size_bytes']:raise ValueError('Archive size mismatch: '+path.name)
        datasets='-datasets-' in path.name;source_only='-source-' in path.name
        expected=set(data) if datasets else public if source_only else None
        prefix='' if datasets else 'ufc-matchup-analyzer/' if source_only else 'UFC Matchup Analyzer/'
        with zipfile.ZipFile(path) as archive:
            names=archive.namelist()
            if expected is None:
                portable=json.loads(archive.read(prefix+'PACKAGE_MANIFEST.json'))
                portable_hashes={x['path']:x['sha256'] for x in portable['files']}
                expected=set(portable_hashes)|{'PACKAGE_MANIFEST.json'}
                if portable['version']!=listing['version']:raise ValueError('Portable manifest version mismatch')
            if len(names)!=len(set(names)) or set(names)!={prefix+x for x in expected}:raise ValueError('Unexpected archive inventory: '+path.name)
            bad=archive.testzip()
            if bad:raise ValueError('Archive CRC failed: '+bad)
            import hashlib
            for rel in expected:
                actual=hashlib.sha256(archive.read(prefix+rel)).hexdigest()
                wanted=data[rel] if datasets else digest(ROOT/rel) if source_only else actual if rel=='PACKAGE_MANIFEST.json' else portable_hashes[rel]
                if actual!=wanted:raise ValueError('Member hash mismatch: '+rel)
            count+=len(names)
        print('PASS: '+path.name)
    print(f'PASS: {len(listing["archives"])} archive hashes; {count} exact member hashes and CRCs; source/data/portable inventories verified.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,zipfile.BadZipFile) as exc:print(str(exc),file=sys.stderr);raise SystemExit(1)
