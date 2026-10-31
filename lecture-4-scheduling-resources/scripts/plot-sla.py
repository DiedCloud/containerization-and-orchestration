"""Plot client p95/errors from saved windows or a k6 JSON stream."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('experiment', choices=['cpu', 'memory'])
parser.add_argument('--input', type=Path, help='Raw k6 --out json file; otherwise use evidence windows')
parser.add_argument('--events', type=Path, help='JSON list of {phase, time} markers')
parser.add_argument('--output', type=Path, default=Path('results'))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
args.output.mkdir(parents=True, exist_ok=True)
if args.input:
    buckets = defaultdict(lambda: {'latency': [], 'errors': []})
    with args.input.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row.get('type') != 'Point' or row['metric'] not in ['http_req_duration', 'http_req_failed']:
                continue
            timestamp = datetime.fromisoformat(row['data']['time'].replace('Z', '+00:00')).timestamp()
            key = 'latency' if row['metric'] == 'http_req_duration' else 'errors'
            buckets[int(timestamp // 10) * 10][key].append(row['data']['value'])
    rows = [{'time': t, 'count': len(v['latency']),
             'p95_ms': float(np.percentile(v['latency'], 95)) if v['latency'] else None,
             'error_rate': float(np.mean(v['errors'])) if v['errors'] else None}
            for t, v in sorted(buckets.items())]
    (args.output / f'sla-{args.experiment}-windows.json').write_text(json.dumps(rows, indent=2) + '\n')
    events = json.loads(args.events.read_text()) if args.events else []
else:
    rows = json.loads((root / f'evidence/sla-{args.experiment}-windows.json').read_text())
    events = json.loads((args.events or root / 'evidence/sla-events.json').read_text())
if not rows:
    raise SystemExit('No k6 observations found')
labels = {'cpu-fill-start': 'batch requests increased', 'batch-preempted': 'batch preempted by API',
          'cpu-pressure-end': 'normal profile restored', 'memory-pressure-start': 'batch memory ramp started',
          'batch-evicted': 'MemoryPressure + batch eviction', 'memory-pressure-end': 'normal profile restored',
          'oom-control-start': 'batch OOM control', 'oom-control-end': 'OOM control finished'}
times = [datetime.fromtimestamp(r['time'], timezone.utc) for r in rows]
fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True, layout='constrained')
axes[0].plot(times, [r['p95_ms'] for r in rows], marker='.', label='Client p95 / 10s window')
axes[0].axhline(300, color='red', linestyle='--', label='SLA 300 ms')
axes[0].set(ylabel='Latency, ms', ylim=(0, max(330, max(r['p95_ms'] or 0 for r in rows) * 1.1)))
axes[1].plot(times, [100 * r['error_rate'] if r['error_rate'] is not None else float('nan') for r in rows],
             marker='.', label='HTTP errors / 10s window')
axes[1].axhline(1, color='red', linestyle='--', label='SLA 1%')
axes[1].set(ylabel='Errors, %', xlabel='Time UTC',
            ylim=(0, max(1.2, max(100 * (r['error_rate'] or 0) for r in rows) * 1.1)))
for ax in axes:
    for event in events:
        moment = datetime.fromtimestamp(event['time'], timezone.utc)
        if event['phase'] in labels and times[0] <= moment <= times[-1]:
            ax.axvline(moment, color='gray', linestyle=':', alpha=.5)
            if ax is axes[0]:
                ax.text(moment, ax.get_ylim()[1] * .95, labels[event['phase']], rotation=90, fontsize=8, va='top')
    ax.grid(alpha=.2)
    ax.legend(loc='upper right')
axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S', tz=timezone.utc))
fig.suptitle(f'{args.experiment}: client latency and errors under load')
path = args.output / f'{args.experiment}-sla.png'
fig.savefig(path, dpi=160)
plt.close(fig)
print(path)
