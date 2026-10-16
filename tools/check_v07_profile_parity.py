"""Parent/export parity for a development-period debut and synthetic profiles."""
import argparse
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest


def main():
    parser=argparse.ArgumentParser()
    for name in ('parent','app','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();parent=args.parent.resolve();app=args.app.resolve();out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    for row in json.loads((app/'dataset_manifest.json').read_text())['files']:
        assert digest(parent/row['path'])==digest(app/row['path'])
    profile=out/'synthetic-qa-profiles.csv'
    with profile.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['fighter','height_cm','reach_cm','stance','dob','weight_lbs'])
        writer.writeheader()
        writer.writerows([dict(fighter='V07 QA Profile A',height_cm=170,reach_cm=174,stance='Orthodox',dob='1995-01-01',weight_lbs=125),
            dict(fighter='V07 QA Profile B',height_cm=163,reach_cm=168,stance='Southpaw',dob='1997-01-01',weight_lbs=125)])
    stats=list(csv.DictReader((app/'womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv').open(encoding='utf-8-sig')))
    debut=min((row for row in stats if row['fighter']=='Melissa Mullins'),key=lambda row:row['event_date'])
    assert debut['event_date'][:10]<'2025-09-27', 'Do not inspect a new final-cohort prediction before development review'
    cases=[('development-debut',['Melissa Mullins',debut['opponent']],debut['event_date'][:10],debut['division'],None),
           ('synthetic-manual',['V07 QA Profile A','V07 QA Profile B'],'2026-10-17',"Women's Flyweight",profile)]
    results=[]
    for label,names,date,division,manual in cases:
        common=['--fighter-a',names[0],'--fighter-b',names[1],'--fight-date',date,'--division',division]
        parent_cmd=[sys.executable,str(ROOT/'tools/run_parent_women.py'),'--parent',str(parent),*common,
                    '--profiles',str(manual or parent/'womens_ufc_model/output_quality_fixed/ufc_womens_fighter_profiles.csv'),
                    '--quiet-diagnostics','--json-out',str(out/(label+'-parent.json'))]
        if manual:parent_cmd+=['--allow-manual-profile-fallback']
        app_cmd=[sys.executable,str(app/'ufc_matchup_analyzer.py'),'predict','women',*common,
                 '--workers','1','--force-recalculate','--out',str(out/(label+'-app.json'))]
        if manual:app_cmd+=['--profiles',str(manual)]
        for origin,cmd,cwd in [('parent',parent_cmd,parent/'womens_ufc_model'),('app',app_cmd,app)]:
            with (out/(label+'-'+origin+'.log')).open('w',encoding='utf-8') as stream:
                subprocess.run(cmd,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=1200)
        original=json.loads((out/(label+'-parent.json')).read_text());public=json.loads((out/(label+'-app.json')).read_text())
        assert math.isclose(original['fighter_a_win_probability'],public['fighter_a_win_probability'],rel_tol=0,abs_tol=1e-12)
        assert original['fold_audit']==public['fold_audit']
        assert public['coverage']['a']['fights']==0
        if manual:
            assert public['coverage']['b']['fights']==0 and public['manual_profile_fallback_used']
        results.append(dict(case=label,status='PASS',probability=public['fighter_a_win_probability'],eligible_a_bouts=0,
            manual_profile_fallback=bool(public.get('manual_profile_fallback_used'))))
        atomic_json(out/'results.json',dict(status='RUNNING',cases=results));print(label,'PASS',flush=True)
    atomic_json(out/'results.json',dict(status='PASS',cases=results,final_cohort_predictions_consulted=False))


if __name__=='__main__':main()
