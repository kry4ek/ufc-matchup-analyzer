"""Render reviewed calibration bins with Matplotlib; no model fitting occurs.

This optional development tool uses Matplotlib, outside the portable runtime.
"""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from analyzer_history import fingerprint
from analyzer_support import atomic_json,digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    value=json.loads(args.report.read_text())
    assert value['integrity']==fingerprint({k:v for k,v in value.items() if k!='integrity'})
    args.out.mkdir(parents=True,exist_ok=True)
    records=[]
    for sex,model in value['models'].items():
        rows=[row for row in model['calibration'] if row['count']]
        total=sum(row['count'] for row in rows)
        fig,ax=plt.subplots(figsize=(7,5.3),layout='constrained')
        ax.plot([0,1],[0,1],color='#88929e',linestyle='--',linewidth=1,label='Perfect calibration')
        ax.scatter([r['mean_probability'] for r in rows],[r['observed_rate'] for r in rows],
                   color='#286a9a',s=44,zorder=3,label='Observed nonempty bins')
        for row in rows:
            x,y=row['mean_probability'],row['observed_rate']
            ax.annotate('n='+str(row['count']),(x,y),xytext=(-8 if x>.85 else 8,-16 if y>.85 else 8),
                        textcoords='offset points',ha='right' if x>.85 else 'left',fontsize=9)
        ax.set(xlim=(0,1),ylim=(0,1),xlabel='Mean forecast probability',ylabel='Observed win rate')
        ax.xaxis.set_major_formatter(PercentFormatter(1))
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        dates=model['event_dates']
        ax.set_title(sex.title()+f' — final retrospective cohort\n{total} bouts across '+str(len(dates))+
                     ' dates · '+min(dates)+' to '+max(dates),fontsize=11)
        ax.grid(alpha=.18);ax.legend(loc='upper left',fontsize=9)
        fig.supxlabel('Fixed five-bin summary; empty bins omitted. Repeated fighters remain dependent.',fontsize=8)
        name='model-validation-v07-'+sex
        for extension in ('png','svg'):
            target=args.out/(name+'.'+extension)
            fig.savefig(target,dpi=200)
            records.append(dict(path=target.name,sha256=digest(target)))
        plt.close(fig)
    atomic_json(args.out/'PLOT_RENDERING.json',dict(status='PASS',input_sha256=digest(args.report),
        matplotlib=matplotlib.__version__,python=sys.version,scope='Charts only; model evaluation uses its separately pinned runtime',files=records))
    print('Rendered two calibration figures, PNG and SVG')


if __name__=='__main__':main()
