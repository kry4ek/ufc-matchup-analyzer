"""Checked scalar fast path in the parent; numeric behavior remains unchanged."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);a=p.parse_args()
    relative='mens_ufc_model/src/features/mens_features.py';path=a.parent/relative
    baseline=a.parent/'work/v07-performance-baseline'/relative
    if baseline.exists():raise ValueError('Original is already preserved; inspect rather than reapply')
    source=path.read_text(encoding='utf-8')
    old='''def _num(value: Any, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(parsed) else float(parsed)'''
    new='''def _num(value: Any, default: float = 0.0) -> float:
    # Parsed CSV statistics already contain numeric scalars. Avoid constructing
    # a one-element pandas Series for every value in every historical bout.
    # Preserve the original parser for strings and other nonnumeric objects.
    if isinstance(value, (int, float, np.integer, np.floating)):
        return default if pd.isna(value) else float(value)
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(parsed) else float(parsed)'''
    if source.count(old)!=1:raise ValueError('Numeric conversion baseline differs')
    changed=source.replace(old,new);compile(changed,str(path),'exec')
    baseline.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,baseline)
    path.write_text(changed,encoding='utf-8',newline='\n')
    (a.parent/'work/v07-performance-baseline/change.json').write_text(json.dumps(dict(path=relative,
        before=sha(baseline),after=sha(path),scope='Numeric scalar conversion only; generic parser retained'),indent=2)+'\n')
    print('Checked parent numeric fast path applied; original retained')

if __name__=='__main__':main()
