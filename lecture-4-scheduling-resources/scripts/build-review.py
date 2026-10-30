"""Build a local screenshot viewer from measured evidence, without replaying faults.

Run with Python + matplotlib/numpy (the KRR tools container provides these).
The viewer explicitly shows archived observations, not live Kubernetes output.
"""
from collections import defaultdict
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

root=Path(__file__).resolve().parents[1]
evidence=root/'evidence'
phases=json.loads((evidence/'phases.json').read_text())
plt.rcParams.update({'font.size':11})
for name in ['06-cpu','07-memory']:
    rows=defaultdict(lambda:{'latency':[],'errors':[]})
    raw=root/'artifacts.local'/f'{name}.json'
    for line in raw.open():
        row=json.loads(line)
        if row.get('type')!='Point':continue
        metric=row['metric'];data=row['data']
        if metric not in ['http_req_duration','http_req_failed']:continue
        stamp=datetime.fromisoformat(data['time'].replace('Z','+00:00')).timestamp()
        bucket=int(stamp//10)*10
        rows[bucket]['latency' if metric=='http_req_duration' else 'errors'].append(data['value'])
    compact=[{'time':t,'count':len(v['latency']),'p95_ms':float(np.percentile(v['latency'],95)) if v['latency'] else None,
              'error_rate':float(np.mean(v['errors'])) if v['errors'] else None} for t,v in sorted(rows.items())]
    (evidence/f'{name}-windows.json').write_text(json.dumps(compact,indent=2)+'\n')
    fig,axes=plt.subplots(2,1,figsize=(13,7),sharex=True,layout='constrained')
    times=[datetime.fromtimestamp(r['time'],timezone.utc) for r in compact]
    axes[0].plot(times,[r['p95_ms'] for r in compact],color='#176bba',marker='.',label='Client p95 / 10s window')
    axes[0].axhline(300,color='#bd3540',linestyle='--',label='SLA 300 ms')
    axes[0].set(ylabel='Latency, ms',ylim=(0,max(330,max(r['p95_ms'] or 0 for r in compact)*1.1)))
    axes[1].plot(times,[100*r['error_rate'] for r in compact],color='#176bba',marker='.',label='HTTP errors / 10s window')
    axes[1].axhline(1,color='#bd3540',linestyle='--',label='SLA 1%')
    axes[1].set(ylabel='Errors, %',ylim=(0,max(1.2,max(100*r['error_rate'] for r in compact)*1.1)),xlabel='Time UTC')
    for ax in axes:
        marker_labels={'cpu-fill-start':'batch requests increased','batch-preempted':'batch preempted by API','cpu-pressure-end':'normal profile restored','memory-pressure-start':'batch memory ramp started','batch-evicted':'MemoryPressure + batch eviction','memory-pressure-end':'normal profile restored','oom-control-start':'batch OOM control','oom-control-end':'OOM control finished'}
        for mark in phases:
            if mark['phase'] not in marker_labels:continue
            t=datetime.fromtimestamp(mark['time'],timezone.utc)
            if times[0]<=t<=times[-1]:
                ax.axvline(t,color='#666',alpha=.5,linestyle=':')
                if ax==axes[0]:ax.text(t,ax.get_ylim()[1]*.95,marker_labels[mark['phase']],rotation=90,fontsize=8,va='top')
        ax.grid(alpha=.2);ax.legend(loc='upper right')
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S',tz=timezone.utc))
    fig.suptitle(f'{name}: 10 POST /order per second, actual k6 samples')
    fig.savefig(evidence/f'{name}-sla.png',dpi=160)
    plt.close(fig)

# Plot the actual Prometheus time series, preserving missing samples as gaps.
ranges=json.loads((evidence/'09-prometheus-ranges.json').read_text())
fig,axes=plt.subplots(4,3,figsize=(17,13),layout='constrained')
for ax,panel in zip(axes.flat,ranges['panels']):
    for series in panel['response']['data']['result']:
        values=series['values'];labels=series['metric']
        label=labels.get('pod',labels.get('phase',labels.get('alertname','value')))
        # query_range omits missing samples. Reindex to the requested grid so
        # matplotlib cannot join two separate firing/traffic episodes.
        grid=[ranges['start']+15*i for i in range(int((ranges['end']-ranges['start'])/15)+1)]
        present={round(t,2):float(v) for t,v in values}
        ax.plot([datetime.fromtimestamp(t,timezone.utc) for t in grid],[present.get(round(t,2),float('nan')) for t in grid],label=label,linewidth=1)
    ax.set_title(panel['title'],fontsize=10);ax.grid(alpha=.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=timezone.utc))
    if panel['title'].startswith('Orders p95'):ax.axhline(.3,color='red',linestyle='--')
    if panel['title'].startswith('Order errors'):ax.axhline(.01,color='red',linestyle='--')
    if len(panel['response']['data']['result'])<6 and panel['response']['data']['result']:ax.legend(fontsize=6,loc='upper left')
fig.suptitle('Archived Prometheus dashboard — actual query_range responses (UTC)')
fig.savefig(evidence/'09-dashboard.png',dpi=150);plt.close(fig)

sections=[('1. Реплики на разных нодах','04-spread.txt'),('2. Рекомендации krr','03-krr-summary.md'),
          ('3. QoS, priority и PDB','05-guarantees.txt'),('4. Pending: Insufficient cpu','06-pending.txt'),
          ('5. Preemption: batch уступает API','06-preemption.txt'),('6. MemoryPressure и eviction','07-eviction.txt'),
          ('7. Контроль: OOMKilled по своему лимиту','07-oom-control.txt')]
def compact_snapshot(file):
    text=(evidence/file).read_text()
    if not file.endswith('.txt'):return text
    focus = ['Preempted'] if file.startswith('06-preemption') else ['FailedScheduling', 'Insufficient cpu'] if file.startswith('06-pending') else ['Evicted','EvictionThresholdMet','MemoryPressure'] if file.startswith('07-eviction') else []
    if not focus:return text
    lines=[]
    in_events=False
    for line in text.splitlines():
        if line.startswith('$ kubectl'):
            in_events='get events' in line
            lines.append(line)
        elif not in_events or any(key in line for key in focus) or line.startswith('LAST SEEN'):
            lines.append(line)
    return '\n'.join(lines)+'\n'

body=['<h1>Лабораторная 4 — сохранённые результаты</h1><p>Архив реальных наблюдений, не текущее состояние kubectl. Каждый снимок содержит дату и команды. Кластер после экспериментов восстановлен. Масштаб страницы можно менять Ctrl+/Ctrl−; F11 — полный экран.</p>']
for title,file in sections:
    body.append(f'<section><h2>{title}</h2><p>Источник: evidence/{file}</p><pre>{html.escape(compact_snapshot(file))}</pre></section>')
for name in ['06-cpu','07-memory']:
    body.append(f'<section><h2>SLA: {name}</h2><img src="evidence/{name}-sla.png"><pre>{html.escape((evidence/f"{name}-k6.txt").read_text())}</pre></section>')
body.append('<section><h2>Дашборд: сохранённые ряды Prometheus</h2><img src="evidence/09-dashboard.png"></section>')
alert=json.loads((evidence/'09-ShopBatchUnschedulable-firing.json').read_text())
body.append('<section><h2>Алерт в firing</h2><p>Реальный ответ API Prometheus, сохранён во время Pending batch.</p><pre>'+html.escape(json.dumps(alert,ensure_ascii=False,indent=2))+'</pre></section>')
(root/'REVIEW.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Lab 4 evidence</title><style>body{margin:32px auto;max-width:1500px;font:17px system-ui;background:#f1f4f8;color:#172232}section{background:white;padding:24px;margin:32px 0;border-radius:12px;box-shadow:0 3px 15px #ccd4df}pre{font:13px/1.55 monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#101b2c;color:#eef5ff;padding:20px;border-radius:8px}img{width:100%;height:auto}h2{margin-top:0}</style>'+''.join(body)+'</html>')
print('Built REVIEW.html and three standalone charts from actual measurements')
