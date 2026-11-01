"""Render the recorded measurements; capture the displayed figure with Spectacle."""
import argparse,json
from pathlib import Path
import matplotlib.pyplot as plt
p=argparse.ArgumentParser();p.add_argument('kind',choices=['flaky','bad','good','cost']);a=p.parse_args()
r=Path(__file__).resolve().parents[1]
plt.rcParams.update({'font.size':14,'axes.grid':True,'figure.facecolor':'white'})
fig,ax=plt.subplots(figsize=(14,7),layout='constrained')
if a.kind=='flaky':
    data=json.loads((r/'evidence/flaky.json').read_text());start=data['start']
    for s in data['backend_error_series']:
        ax.plot([float(t)-start for t,v in s['values']],[float(v)*100 for t,v in s['values']],label='Backend 5xx (Linkerd inbound, 30s rate)',linewidth=2)
    ax.plot([t-start for t,v in data['client_windows']],[v*100 for t,v in data['client_windows']],label='Client errors (10s windows)',linewidth=2)
    ax.set(xlabel='Seconds',ylabel='Errors, %',title=f'FLAKY=true, 30% simulated backend failures; {data["errors"]}/{data["requests"]} client errors',ylim=(-1,40));ax.legend()
elif a.kind in ['bad','good']:
    data=json.loads((r/f'evidence/{a.kind}.json').read_text());start=data['start']
    ax.step([x['time']-start for x in data['weights']],[x['weight'] for x in data['weights']],where='post',label='Configured v2 traffic weight',linewidth=2)
    for key,label in [('error','v2 backend 5xx, 30s rate'),('traffic','Observed v2 traffic share, 30s rate')]:
        for s in data[key]: ax.plot([float(t)-start for t,v in s['values']],[float(v)*100 for t,v in s['values']],label=label,linewidth=2)
    for x in data['gate']:
        if x.get('decision') in ['rollback','promote']:
            ax.axvline(x['time']-start,color='gray',alpha=.5,linestyle='--')
    ax.set(xlabel='Seconds',ylabel='Percent',ylim=(-3,105),title='Automatic rollback: FAIL=true' if a.kind=='bad' else 'Automatic promotion: healthy v2');ax.legend(loc='center right')
else:
    base=json.loads((r/'evidence/baseline.json').read_text());mesh=json.loads((r/'evidence/mesh.json').read_text())
    fig.clear();axes=fig.subplots(1,3)
    for axis,key,title,scale in zip(axes,['p95_ms','cpu_cores','memory_bytes'],['Order p95, ms','API pods CPU, millicores','API pods working set, MiB'],[1,1000,1/1048576]):
        vals=[(sum(x['value'] for x in d[key]) if isinstance(d[key],list) else d[key])*scale for d in [base,mesh]]
        bars=axis.bar(['Baseline','Mesh'],vals,color=['#5594c7','#e89947']);axis.bar_label(bars,fmt='%.2f');axis.set_title(title);axis.set_ylim(0,max(vals)*1.25)
    fig.suptitle('Same workload: 20 orders/s, 120 seconds, 2 API v1 replicas')
fig.savefig(f'/tmp/lab6-{a.kind}.png',dpi=140)
