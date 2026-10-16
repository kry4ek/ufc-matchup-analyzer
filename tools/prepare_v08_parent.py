"""Narrow parent-first row-iteration optimization and full-history parity audit."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest

FILES=('mens_ufc_model/src/features/mens_live_v2_features.py','mens_ufc_model/src/features/mens_live_v3_bayes_features.py')
def transform(text):
    helper='''def _record_rows(frame):
    # Preserve column order and scalar values without constructing a Series per row.
    columns = tuple(frame.columns)
    return (dict(zip(columns, values)) for values in frame.to_numpy(dtype=object))


'''
    marker='def _process_date_group(' if 'def _process_date_group(' in text else 'def _identity_maps('
    result=text.replace(marker,helper+marker,1).replace('for _, row in stats.iterrows():','for row in _record_rows(stats):')
    if 'def _process_date_group(' in text:
        marker='    date_snapshots: dict[tuple[str, str], dict[str, Any]] = {}'
        result=result.replace(marker,'    rows = tuple(_record_rows(date_group))\n'+marker)
        return result.replace('for _, row in date_group.iterrows():','for row in rows:')
    return result.replace('for _, row in date_group.iterrows():','for row in _record_rows(date_group):')

def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--apply-parent',action='store_true');p.add_argument('--revise-parent',action='store_true');p.add_argument('--verify',action='store_true');p.add_argument('--export',action='store_true');a=p.parse_args()
    parent=a.parent.resolve();out=ROOT/'work/v0.8/parent-originals'
    if a.apply_parent:
        if out.exists():raise ValueError('Originals already captured; inspect checkpoint before retrying')
        changes=[]
        for rel in FILES:
            path=parent/rel;text=path.read_text(encoding='utf-8');new=transform(text)
            expected=2
            if text.count('.iterrows():')<expected or new==text:raise ValueError('Parent row loops changed')
            before=out/rel;before.parent.mkdir(parents=True,exist_ok=True);before.write_text(text,encoding='utf-8',newline='\n')
            compile(new,str(path),'exec');path.write_text(new,encoding='utf-8',newline='\n')
            changes.append(dict(path=rel,before=digest(before),after=digest(path)))
        atomic_json(out/'change.json',dict(status='PARENT_PATCHED_NOT_EXPORTED',files=changes))
        print('Parent iteration optimization prepared; originals preserved',flush=True)
    if a.revise_parent:
        for rel in FILES:
            original=(out/rel).read_text(encoding='utf-8');path=parent/rel;current=path.read_text(encoding='utf-8')
            previous=original.replace('for _, row in date_group.iterrows():','for row in date_group.to_dict(orient="records"):').replace('for _, row in stats.iterrows():','for row in stats.to_dict(orient="records"):')
            if current!=previous:raise ValueError('Parent iteration-1 context differs; refusing to overwrite')
            before=ROOT/'work/v0.8/parent-iteration-1'/rel;before.parent.mkdir(parents=True,exist_ok=True);before.write_text(current,encoding='utf-8')
            changed=transform(original);compile(changed,str(path),'exec');path.write_text(changed,encoding='utf-8',newline='\n')
        old_report=out/'parity.json'
        if old_report.exists():(ROOT/'work/v0.8/parent-iteration-1/parity.json').write_bytes(old_report.read_bytes())
        print('Revised iteration uses one object-array conversion and reuses dated rows across both passes',flush=True)
    if a.verify:
        import pandas as pd
        from tools.check_v06_performance import equal
        sys.path.insert(0,str(parent/'mens_ufc_model'))
        from src.features import mens_live_v2_features as v2,mens_live_v3_bayes_features as v3
        old=[]
        for i,rel in enumerate(FILES):
            spec=importlib.util.spec_from_file_location('original_v08_'+str(i),out/rel)
            module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);old.append(module)
        fights=pd.read_csv(parent/'mens_ufc_model/data/raw/ufcstats_men/fights.csv')
        stats=pd.read_csv(parent/'mens_ufc_model/data/raw/ufcstats_men/fight_stats.csv')
        context=v3.prepare_live_v3_bayes_context(fights,stats)
        equal(old[1]._identity_maps(context.base_context.stats),v3._identity_maps(context.base_context.stats))
        rows=[]
        for date in ('2000-01-01','2020-01-01','2026-10-10'):
            for name,previous,current,ctx in (('base',old[1]._recompute_base_state_before,v3._recompute_base_state_before,context.base_context),('advanced',old[0]._recompute_state_before,v2._recompute_state_before,context.v2_context)):
                started=time.monotonic();reference=previous(ctx,pd.Timestamp(date));old_seconds=time.monotonic()-started
                started=time.monotonic();candidate=current(ctx,pd.Timestamp(date));new_seconds=time.monotonic()-started
                equal(reference,candidate)
                rows.append(dict(date=date,history=name,reference_seconds=old_seconds,candidate_seconds=new_seconds,status='PASS'))
                atomic_json(out/'parity.json',dict(status='RUNNING',cases=rows));print(name,date,old_seconds,new_seconds,flush=True)
        atomic_json(out/'parity.json',dict(status='PASS',cases=rows,method='Every base and advanced history plus global/division totals at three cutoffs; same-date grouping retained; identity maps equal.'))
    if a.export:
        if json.loads((out/'parity.json').read_text())['status']!='PASS':raise ValueError('Parent audit not complete')
        exports=[]
        for rel in FILES:
            path=ROOT/rel;text=path.read_text(encoding='utf-8');changed=transform(text)
            original=(out/rel).read_text(encoding='utf-8');parent_text=(parent/rel).read_text(encoding='utf-8')
            if transform(original)!=parent_text:raise ValueError('Parent changed since audit')
            if changed==text:raise ValueError('App already exported or patch context differs')
            path.write_text(changed,encoding='utf-8',newline='\n');exports.append(dict(path=rel,parent_sha256=digest(parent/rel),app_sha256=digest(path)))
        atomic_json(out/'export.json',dict(status='PASS',files=exports,scope='Only audited row-iteration replacements; app progress adapters preserved.'))
        print('Audited parent loops exported',flush=True)
if __name__=='__main__':main()
