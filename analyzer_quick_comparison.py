"""Lightweight evidence from validated source history, without fitting a model."""
from __future__ import annotations
import csv
import datetime as dt
from pathlib import Path
from analyzer_results import _number
from analyzer_history import fingerprint, utc_now

def build_quick(root, request, catalog, recent, coverage, context, profiles_path=None):
    root = Path(root)
    path = root / ('mens_ufc_model/data/raw/ufcstats_men/fighters.csv' if request['sex']=='men'
                   else 'womens_ufc_model/output_quality_fixed/ufc_womens_fighter_profiles.csv')
    profiles = {}
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            identifier = row.get('fighter_id') or row.get('profile_url','').rstrip('/').rsplit('/',1)[-1]
            profiles[identifier] = row
    manual={}
    if profiles_path:
        from analyzer_catalog import key
        with Path(profiles_path).open(encoding='utf-8-sig',newline='') as stream:
            manual={key(r.get('fighter',r.get('fighter_name',''))):r for r in csv.DictReader(stream)}
    result = dict(schema_version=1, analyzer_version=__import__('analyzer_support').VERSION,
                  fighter_a=request['fighter_a'], fighter_b=request['fighter_b'],
                  fighter_a_id=request['fighter_a_id'], fighter_b_id=request['fighter_b_id'],
                  division=request['division'], fight_date=request['fight_date'],
                  model_version=context['engine'], result_state='initial', quick_comparison=True,
                  generated_at=utc_now(), calculation_request=request,
                  calculation_fingerprint=fingerprint(context), recent_fights=recent, coverage=coverage,
                  warnings=['Initial evidence only; advanced statistics are still being prepared.',
                            'Profile measurements reflect the installed snapshot, including later corrections.'],
                  history_cutoff=request['fight_date'], training_cutoff=request['effective_cutoff'])
    for side in ('a','b'):
        row = profiles.get(request['fighter_'+side+'_id'], {})
        if profiles_path:
            row=dict(row,**manual.get(key(request['fighter_'+side]),{}))
        info = coverage[side]
        snapshot = {field:_number(row.get(field)) for field in ('height_cm','reach_cm')}
        snapshot['stance'] = row.get('stance') or None
        birth = row.get('date_of_birth') or row.get('dob')
        try:
            born=dt.date.fromisoformat(birth); date=dt.date.fromisoformat(request['fight_date'])
            snapshot['age_at_fight']=(date-born).days/365.25 if born<=date else None
        except (TypeError,ValueError): snapshot['age_at_fight']=None
        # Coverage includes draws/NCs; its labels distinguish it from engine-specific counts.
        snapshot['recorded_eligible_bouts']=info['fights']
        snapshot['recorded_division_bouts']=info['division_fights']
        snapshot['missing_profile_fields']=[field for field in ('height_cm','reach_cm','stance','age_at_fight') if snapshot.get(field) is None]
        result['fighter_'+side+'_comparison']=snapshot
    return result

def format_quick(payload):
    from analyzer_results import _value
    lines=['INITIAL COMPARISON — partial evidence; no completed prediction ('+payload.get('result_state','initial')+')',
           'History: event_date < '+payload['fight_date'],
           'Training cutoff: '+str(payload.get('training_cutoff','Unknown'))]
    for side in ('a','b'):
        values=payload['fighter_'+side+'_comparison']; info=payload['coverage'][side]
        lines.append(payload['fighter_'+side]+': '+str(info['fights'])+' eligible recorded bouts, '+str(info['division_fights'])+' in selected division.')
        lines.append('Height: '+_value(values.get('height_cm'),'number')+' cm; reach: '+_value(values.get('reach_cm'),'number')+' cm; stance: '+str(values.get('stance') or 'N/A'))
    return '\n'.join(lines)
