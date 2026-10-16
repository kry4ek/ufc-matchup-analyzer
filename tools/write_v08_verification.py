"""Write release notes from completed local evidence, retaining pending checks."""
import json
import platform
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json

def read(path):
    path=ROOT/path
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(status='PENDING')

def suite(path):
    p=ROOT/path
    if not p.exists():return dict(status='PENDING')
    text=p.read_text(encoding='utf-8',errors='replace');matches=re.findall(r'Ran (\d+) tests in ([\d.]+)s',text)
    if not matches:return dict(status='PENDING')
    count,seconds=matches[-1]
    return dict(status='PASS' if re.search(r'^OK(?: \(.*\))?\s*$',text,re.M) else 'FAIL',tests=int(count),seconds=float(seconds),skips=len(re.findall(r'\.\.\. skipped ',text)))

def main():
    evidence=dict(version='0.8.0',date='2026-10-16',scope='Local experimental app iteration; prospective work excluded; clean OS/actual alternate DPI deferred; no publication or remote CI claimed',
        environment=dict(python='3.14.7 bundled runtime',windows=platform.platform()),
        regression=suite('work/v0.8/final-tests.log'),source_only=suite('work/v0.8/source-tests.log'),
        parent_history_parity=read('work/v0.8/parent-originals/parity.json'),
        native_ui=read('work/v0.8/ui/verification.json'),history_ui=read('work/v0.8/history-ui.json'),
        print_pages=read('work/v0.8/print/page-counts.json'),benchmarks={})
    evidence['native_exe']=read('work/v0.8/exe-startup.json')
    evidence['upgrade']=read('work/v0.8/upgrade/check.json')
    native=read('work/v0.8/native-dependencies.json')
    evidence['native_dependencies']={k:native.get(k) for k in ('status','pe_files','missing')}
    evidence['portable_matrix']={}
    for sex in ('men','women'):
        v=read('work/v0.8/portable/'+sex+'.json')
        evidence['portable_matrix'][sex]=dict(status=v.get('status'),runs=[{k:r.get(k) for k in ('case','seconds','probability','render_seconds','comparison_navigation_seconds','copy_and_save','visible_owned_console_windows')} for r in v.get('runs',[])])
    lines=['# v0.8 performance measurements','','All values are measured on the available computer with the same bundled runtime and matching data. Fresh computations bypass saved-result and calculation-cache reads. OS file caches and unrelated system load were not controlled; these are not cold-boot claims. Three alternating pairs support medians and observed ranges, not reliable tail-percentile claims.','',
        '| Journey | Reference median (s) | Candidate median (s) | Change | Reference range | Candidate range |','| --- | ---: | ---: | ---: | --- | --- |']
    for mode,sex in [('startup','men'),('compare','men'),('compare','women'),('predict','men'),('predict','women')]:
        name=mode+'-'+sex
        path='work/v0.8/final-benchmarks/'+name+'.json'
        if mode=='startup' and (ROOT/'work/v0.8/startup-idle.json').exists():path='work/v0.8/startup-idle.json'
        v=read(path);evidence['benchmarks'][name]=v
        if v.get('status')!='PASS':lines.append('| '+name+' | Pending | Pending | Pending | | |');continue
        bounds={key:(min(r['seconds'] for r in v['runs'] if r['method']==key),max(r['seconds'] for r in v['runs'] if r['method']==key)) for key in ('reference','candidate')}
        m=v['medians'];change=v['reduction_percent']
        change_label=f"{abs(change):.1f}% "+('faster' if change>=0 else 'slower')
        lines.append(f"| {name} | {m['reference']:.3f} | {m['candidate']:.3f} | {change_label} | {bounds['reference'][0]:.3f}–{bounds['reference'][1]:.3f} | {bounds['candidate'][0]:.3f}–{bounds['candidate'][1]:.3f} |")
    lines+=['','Positive change means lower latency. Any negative change is a slowdown, not an improvement. The full raw run list is retained in `verification_evidence.json` and the local work evidence. The first startup set overlapped the native regression suite; an idle rerun, when present, replaces it in this table. Startup includes dependency imports and compute-readiness checks, while saved-report availability and first visible window are separate interactions.','',
        'The original targets were at least 25% lower startup/comparison medians when the baseline exceeded five seconds, no reproducible full-prediction regression over 5%, and responsive native interactions. Targets are reported honestly: the women’s statistics-only route did not show the requested 25% gain in the first complete set. No model policy or comparison field was removed to manufacture a timing result.','',
        'The row-iteration optimization was made in the research parent first. Every base and advanced fighter history, global/division total and identity mapping agreed at three dated cutoffs before export. The first dictionary-conversion variant preserved values but was slower; it was retained locally and replaced before promotion. End-to-end benchmark PASS requires unchanged raw comparison values and probabilities within 1e-12.','']
    history=evidence['history_ui']
    if history.get('status')=='PASS':lines.append(f"Near-capacity history: {history['history_bytes']:,} bytes across 50 entries; opening the dialog returned in {history['open_dialog_callback_seconds']:.3f} s; selected report opened in {history['open_selected_seconds']:.3f} s. Maximum observed event-loop gap during loading was {history['max_event_loop_gap_seconds']:.3f} s.")
    ui=evidence['native_ui']
    if ui.get('status')=='PASS':
        values=ui['interactions'];lines.append('Native bout expansion ranged %.3f–%.3f s; recent-window changes %.3f–%.3f s. Values include layout processing; cases over the 150 ms planning target remain visible in the evidence.'%(min(r['bout_expand_seconds'] for r in values),max(r['bout_expand_seconds'] for r in values),min(r['form_switch_seconds'] for r in values),max(r['form_switch_seconds'] for r in values)))
    exe=evidence['native_exe']
    if exe.get('closed_gracefully'):
        lines.append(f"The actual native EXE showed its first window in {exe['first_visible_seconds']:.3f} s and became compute-ready in {exe['compute_ready_seconds']:.3f} s in the final package check. These individual observations are separate from the repeated startup benchmark and include the available machine's load/library/file-cache conditions.")
    (ROOT/'docs/V0_8_BENCHMARK.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    checks=[('Integrated native regression',evidence['regression']['status']),('Source-only regression',evidence['source_only']['status']),
        ('Parent full-history parity',evidence['parent_history_parity']['status']),('Native v0.8 interactions',ui['status']),('Near-capacity history',history['status']),
        ('Native compact Save dialog',read('work/v0.8/native-compact/check.json').get('status','PENDING')),
        ('Final end-to-end benchmarks and prediction parity','PASS' if all(v.get('status')=='PASS' for v in evidence['benchmarks'].values()) else 'PENDING'),
        ('Offline portable men workflow','PASS' if evidence['portable_matrix']['men']['status']=='PASS' and {'forward','reverse','historical'}.issubset({r['case'] for r in evidence['portable_matrix']['men']['runs']}) else 'PENDING'),
        ('Offline portable women workflow','PASS' if evidence['portable_matrix']['women']['status']=='PASS' and {'forward','reverse','historical'}.issubset({r['case'] for r in evidence['portable_matrix']['women']['runs']}) else 'PENDING'),
        ('Native EXE startup','PASS' if read('work/v0.8/exe-startup.json').get('closed_gracefully') else 'PENDING'),
        ('Genuine legacy import/view/export/undo',read('work/v0.8/upgrade/check.json').get('status','PENDING')),
        ('Native dependency closure',read('work/v0.8/native-dependencies.json').get('status','PENDING')),
        ('Source and data audit',read('work/v0.8/audit.json').get('status','PENDING')),
        ('Archive inventory/hash/CRC checks','RECORDED_EXTERNALLY')]
    evidence['checks']=[dict(name=name,status=status) for name,status in checks]
    evidence['deferred']=['Clean Windows 10/11','Actual alternate Windows display scaling']
    evidence['release_limits']=['Dataset redistribution review_required','Unsigned launcher','Experimental candidate; stable gate not passed','No publication/remote CI requested']
    atomic_json(ROOT/'verification_evidence.json',evidence)
    release=dict(version='0.8.0',status='local_experimental_candidate',checks=[dict(name=n,status=s,required=s!='RECORDED_EXTERNALLY') for n,s in checks]+[
        dict(name=n,status='DEFERRED',required=True) for n in evidence['deferred']]+[
        dict(name='Dataset rights',status='review_required',required=True),dict(name='Signing / stable release',status='PENDING',required=True),
        dict(name='Publication and remote CI',status='NOT_REQUESTED',phase='after_publish',required=True)])
    atomic_json(ROOT/'release_checks.json',release)
    verification=['# v0.8 local verification','','This report covers the five app changes and the available computer. Historical v0.7 model/dataset evaluation is retained separately; it is not a new validation study.','',
        '| Check | Recorded status |','| --- | --- |']+['| '+name+' | '+status+' |' for name,status in checks]
    verification+=['','Implemented behavior: progressive startup and history availability; content-checked structural reuse; audited dated-history iteration; frozen bout/opponent evidence; Last 3/Last 5 versus career; guided refresh preserving the original; and compact offline HTML. See [data contracts](V0_8_DATA_CONTRACTS.md) and [upgrade notes](V0_8_UPGRADE.md).','',
        'Arithmetic checks cover pooled ratios, unequal durations, missing/zero denominators, invalid source values, identity ambiguity, same-size/timestamp source edits, corrupted caches, protected refresh retention and unchanged frozen exports. Native interaction checks cover text sizes, simulated scaling, refresh success/cancellation and displayed-report preservation.','',
        'Four compact fixtures (men, women, statistics-only and legacy) were printed offline on A4 and Letter. The page-count evidence records all eight outputs; inspected rendered samples establish layout readability, not a clean OS certification.','',
        'Clean Windows 10/11 and actual alternative display-scaling tests are deferred at the user’s request. These do not block local delivery. Native tests on this computer and simulated Tk scaling are labelled as such. Dataset rights remain review_required, the launcher is unsigned, and the stable/publication gate remains separate. Prospective tracking is excluded.','',
        'Final archive checksums and independent packaging proof live beside the archives in `POST_BUILD_VERIFICATION.json`; an archive cannot contain its own final hash. RECORDED_EXTERNALLY points to that companion proof and does not stand for an embedded hash. Pending statuses above are not passes. The final handoff lists the completed local artifacts.']
    (ROOT/'docs/V0_8_VERIFICATION.md').write_text('\n'.join(verification)+'\n',encoding='utf-8')
    previous=ROOT/'docs/RELEASE_VERIFICATION_V07.md'
    root=ROOT/'RELEASE_VERIFICATION.md'
    if not previous.exists():previous.write_bytes(root.read_bytes())
    root.write_text('# v0.8 local experimental candidate\n\nCurrent checks are recorded in [v0.8 verification](docs/V0_8_VERIFICATION.md), [performance measurements](docs/V0_8_BENCHMARK.md) and `verification_evidence.json`.\n\nAll five app changes are implemented locally. Clean Windows 10/11 and actual alternative display-scaling checks are deferred; the candidate is not published or stable. Dataset redistribution remains `review_required` and the launcher is unsigned.\n\nHistorical [v0.7 verification](docs/RELEASE_VERIFICATION_V07.md) is preserved separately.\n',encoding='utf-8')
    print(json.dumps(dict(checks=checks),indent=2),flush=True)
if __name__=='__main__':main()
