"""Profile two-pass hashing/CSV scanning against a one-pass stream prototype."""
import argparse,csv,hashlib,io,json,time
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest,manifest

class DigestReader(io.RawIOBase):
    def __init__(self,source):self.source=source;self.sha=hashlib.sha256()
    def readable(self):return True
    def readinto(self,buffer):
        count=self.source.readinto(buffer)
        if count:self.sha.update(memoryview(buffer)[:count])
        return count

def scan(path,combined):
    before=time.monotonic();sha=None
    if not combined:sha=digest(path)
    with path.open('rb') as source:
        wrapper=DigestReader(source) if combined else source
        with io.TextIOWrapper(io.BufferedReader(wrapper),encoding='utf-8-sig',newline='') as text:
            reader=csv.DictReader(text);columns=reader.fieldnames;count=sum(1 for _ in reader)
        if combined:sha=wrapper.sha.hexdigest()
    return dict(seconds=time.monotonic()-before,sha256=sha,rows=count,columns=columns)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--repeat',type=int,default=2);args=parser.parse_args()
    if not 1<=args.repeat<=5:parser.error('repeat must be 1–5')
    runs=[]
    for repeat in range(args.repeat):
        for combined in ((False,True) if repeat%2==0 else (True,False)):
            results=[scan(ROOT/entry['path'],combined) for entry in manifest()['files']]
            for entry,result in zip(manifest()['files'],results):
                assert all(result[field]==entry[field] for field in ('sha256','rows','columns'))
            runs.append(dict(repetition=repeat+1,method='single-pass prototype' if combined else 'separate hashing and CSV scan',seconds=round(sum(r['seconds'] for r in results),3)))
    atomic_json(args.out,dict(status='PASS',runs=runs,scope='Hash/schema/row-count prototype, not a replacement for full semantic validation. Same data, alternating order.'))

if __name__=='__main__':main()
