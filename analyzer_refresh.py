"""Explicit refresh request semantics, independent of widget state."""
import copy
import datetime as dt

def refresh_request(entry,today=False):
    request=entry.get('request',{})
    if request.get('profiles_sha256'):raise ValueError('This analysis needs its original manual profile file. Refresh it through the CLI.')
    fields=('operation','sex','fighter_a','fighter_b','fighter_a_id','fighter_b_id','division','fight_date','workers','as_of_date')
    result={k:request[k] for k in fields if request.get(k) is not None}
    if any(not result.get(k) for k in fields[:8]):raise ValueError('This older report lacks a complete request. Rebuild the matchup explicitly.')
    if result['operation'] not in ('predict','compare') or result['sex'] not in ('men','women'):raise ValueError('Unsupported saved analysis mode')
    if today:result['fight_date']=dt.date.today().isoformat()
    date=dt.date.fromisoformat(result['fight_date'])
    if result.get('as_of_date') and (dt.date.fromisoformat(result['as_of_date'])>=date or dt.date.fromisoformat(result['as_of_date'])>dt.date.today()):raise ValueError('Original as-of date is incompatible with the new matchup date. Edit the matchup explicitly.')
    if result.get('workers')=='automatic':result.pop('workers')
    result.update(skip_saved_result=True,use_cache=True,preserve_history_id=entry.get('id'))
    return result

def captured_entry(payload):
    return dict(id=payload.get('history_id'),created_at=payload.get('generated_at',''),
        request=copy.deepcopy(payload.get('calculation_request',{})),context={},payload=copy.deepcopy(payload))
