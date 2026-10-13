"""Compare bounded women's correction rebuilding against a full fresh rebuild.

Uses complete paired bouts in a small chronological fixture, including later
appearances of the corrected fighter; never modifies installed source data.
"""
import argparse
import importlib.util
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_corrections import rebuild_women
from analyzer_support import atomic_json,digest

def main():
    import pandas as pd
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    source=ROOT/'womens_ufc_model';folder=args.out.parent.resolve()
    if not folder.is_relative_to((ROOT/'work').resolve()) or folder.exists():raise ValueError('Choose a new fixture folder under project work.')
    folder.mkdir(parents=True)
    rel='output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv'
    before_hash=digest(source/rel)
    advanced_rel='output_advanced_features_sig_fixed/ufc_womens_model_training_rows_advanced_sig_fixed.csv'
    stats=pd.read_csv(source/rel);stats['event_date']=pd.to_datetime(stats['event_date'])
    ids=stats[stats['fighter']=='Alexa Grasso'].sort_values('event_date')['fight_id'].tail(5).tolist()
    fixture=stats[stats['fight_id'].isin(ids)].copy()
    assert len(fixture)==10 and fixture['event_date'].nunique()>=4
    original=folder/'original';stage=folder/'bounded'
    for engine in (original,stage):
        engine.mkdir()
        for file in source.glob('*.py'):shutil.copy2(file,engine/file.name)
        for path in (rel,'output_quality_fixed/ufc_womens_fighter_profiles.csv'):
            (engine/path).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/'output_quality_fixed/ufc_womens_fighter_profiles.csv',engine/'output_quality_fixed/ufc_womens_fighter_profiles.csv')
    spec=importlib.util.spec_from_file_location('full_fixture_updater',original/'update_ufc_womens_dataset_incremental.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    predictor=module.import_predictor(str(original/'predict_matchup_advanced.py'))
    seed=pd.read_csv(source/advanced_rel).iloc[:0]
    baseline=module.build_new_training_rows(predictor,seed,fixture,original/'output_quality_fixed/ufc_womens_fighter_profiles.csv',fixture)
    for engine in (original,stage):
        fixture.to_csv(engine/rel,index=False);(engine/advanced_rel).parent.mkdir(parents=True);baseline.to_csv(engine/advanced_rel,index=False)
    changed=ids[1]
    # A real recorded draw can be turned into a decisive fixture result, and
    # decisive bouts can become NC. Both paths rebuild subsequent history.
    mask=fixture['fight_id']==changed
    assert mask.sum()==2
    changed_rows=fixture[mask].sort_values('fighter')
    if changed_rows['result_marker'].isin(['W','L']).all():
        fixture.loc[mask,['result','result_marker','won']]=['nc','NC',float('nan')]
    else:
        for index,result,marker,target in zip(changed_rows.index,['win','loss'],['W','L'],[1,0]):
            fixture.loc[index,['result','result_marker','won']]=[result,marker,target]
    index=changed_rows.index[0];other=changed_rows.index[1]
    for field in ('td_landed','td_attempted'):
        fixture.loc[index,field]+=1;fixture.loc[other,'opponent_'+field]+=1
    fixture.to_csv(stage/rel,index=False)
    rebuild_women(stage,original)
    actual=pd.read_csv(stage/advanced_rel)
    # Construct every expected row afresh, without the correction helper's
    # earliest-date detection, prefix retention or append/replacement logic.
    expected=module.build_new_training_rows(predictor,baseline,fixture,original/'output_quality_fixed/ufc_womens_fighter_profiles.csv',fixture)
    keys=['event_date','fight_id','fighter_a','fighter_b']
    for table in (actual,expected):table['event_date']=pd.to_datetime(table['event_date']).dt.strftime('%Y-%m-%d')
    actual=actual.sort_values(keys).reset_index(drop=True);expected=expected.sort_values(keys).reset_index(drop=True)
    pd.testing.assert_frame_equal(actual,expected,check_dtype=False,atol=1e-10,rtol=1e-12)
    previous=baseline[baseline['fight_id'].isin(ids[2:])].sort_values(keys).reset_index(drop=True)
    subsequent=actual[actual['fight_id'].isin(ids[2:])].sort_values(keys).reset_index(drop=True)
    numeric=[c for c in subsequent if c in previous and pd.api.types.is_numeric_dtype(subsequent[c]) and pd.api.types.is_numeric_dtype(previous[c])]
    changes=[c for c in numeric if not subsequent[c].fillna(-999999).equals(previous[c].fillna(-999999))]
    assert any('elo' in c or 'td_' in c or 'ufc_win_pct' in c for c in changes),'No correction reached later history features'
    assert before_hash==digest(source/rel)
    atomic_json(args.out,dict(status='PASS',source_hash_unchanged=before_hash,fixture_bouts=5,corrected_bout=changed,full_rebuild_rows=len(expected),compared_columns=len(expected.columns),later_changed_columns=changes))

if __name__=='__main__':main()
