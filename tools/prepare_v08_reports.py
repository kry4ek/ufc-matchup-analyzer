"""Create test-only HTML variants for compact report print verification."""
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_compact_report import compact_html
out=ROOT/'work/v0.8/print';out.mkdir(parents=True,exist_ok=True)
fixtures={sex:json.loads((ROOT/f'work/v0.8/ui/{sex}-fixture.json').read_text(encoding='utf-8')) for sex in ('men','women')}
cases=dict(fixtures)
cases['statistics']=dict(copy.deepcopy(fixtures['men']),result_state='comparison')
legacy=copy.deepcopy(fixtures['women']);legacy.pop('bout_details',None);legacy.pop('recent_form',None)
cases['legacy']=legacy
for name,payload in cases.items():
    (out/(name+'.html')).write_text(compact_html(payload),encoding='utf-8')
print('Prepared four review HTML variants',flush=True)
