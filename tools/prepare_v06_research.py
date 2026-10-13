"""Apply a checked performance-only parent change and preserve its original source."""
import argparse
import ast
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest

REL='mens_ufc_model/src/features/mens_live_v2_features.py'
OLD='''    date_snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in date_group.iterrows():
        fighter_id = _clean_id(row.get("fighter_id"))
        if not fighter_id:
            continue
        snap = _fighter_snapshot(row, histories[fighter_id], global_totals, division_totals)
        date_snapshots[(_clean_id(row.get("fight_id")), fighter_id)] = snap
'''
NEW='''    # Only opponent pre-date win percentage is consumed by the update pass.
    # Preserve the frozen date boundary without constructing unused full snapshots.
    date_snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in date_group.iterrows():
        fighter_id = _clean_id(row.get("fighter_id"))
        if not fighter_id:
            continue
        history = histories[fighter_id]
        wins = int(history["wins"])
        completed = wins + int(history["losses"])
        rate = float(wins / completed) if completed > 0 else np.nan
        date_snapshots[(_clean_id(row.get("fight_id")), fighter_id)] = {"ufc_win_pct_before": rate}
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);a=p.parse_args()
    parent=a.parent.resolve();path=parent/REL
    text=path.read_text(encoding='utf-8');baseline=parent/'work/v06-research-baseline'/REL
    spec=json.loads((ROOT/'source_manifest.json').read_text(encoding='utf-8'))
    expected=next(item['source_sha256'] for item in spec['files'] if item['path']==REL)
    if NEW in text and baseline.exists():print('Parent optimization already prepared.');return
    if digest(path)!=expected or text.count(OLD)!=1:raise ValueError('Parent source differs from reviewed baseline; preserve it and reconcile first.')
    baseline.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,baseline)
    updated=text.replace(OLD,NEW,1);ast.parse(updated);path.write_text(updated,encoding='utf-8',newline='\n')
    atomic_json(parent/'work/v06-research-baseline/change.json',dict(path=REL,before=digest(baseline),after=digest(path),reason='Avoid unused per-date full snapshots; same opponent win percentage and chronology.'))
    print('Prepared checked parent optimization; original source retained.')
if __name__=='__main__':main()
