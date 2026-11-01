"""Plot measured client failures and actual pod deletion/IP events together."""
import argparse
import datetime
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--input',type=Path,default=Path('results/client.jsonl'))
p.add_argument('--internal',type=Path,default=Path('results/internal-client.jsonl'))
p.add_argument('--chaos',type=Path,default=Path('results/chaos.jsonl'))
p.add_argument('--output',type=Path,default=Path('results/chaos.png'))
a=p.parse_args()
requests=[json.loads(x) for x in a.input.read_text().splitlines() if x.startswith('{')]
internal=[json.loads(x) for x in a.internal.read_text().splitlines() if x.startswith('{')]
events=[json.loads(x) for x in a.chaos.read_text().splitlines() if x.startswith('{')]
t0=min(r['time'] for r in requests)
windows=[]
for s in range(0,int(max(r['time'] for r in requests)-t0)+1,5):
 rows=[r for r in requests if s<=r['time']-t0<s+5]
 windows.append({'second':s,'requests':len(rows),'failed':sum(not r['ok'] for r in rows)})
gaps=[b['time']-a['time'] for a,b in zip(sorted(requests,key=lambda r:r['time']),sorted(requests,key=lambda r:r['time'])[1:])]
if max(gaps)>3: raise RuntimeError('Measurement interrupted: request start gap exceeds 3s')
fig,(top,bottom)=plt.subplots(2,1,figsize=(14,7),sharex=True,gridspec_kw={'height_ratios':[2,1]})
top.plot([x['second'] for x in windows],[x['requests'] for x in windows],label='NodePort orders / 5 s',color='#198754')
top.plot([x['second'] for x in windows],[x['failed'] for x in windows],label='Failed / 5 s',color='#dc3545',linewidth=3)
top.plot([x['second'] for x in windows],[sum(x['second']<=r['time']-t0<x['second']+5 for r in internal) for x in windows],label='Cluster DNS orders / 5 s',color='#3066be',linestyle='--')
top.set_ylim(-2,max(x['requests'] for x in windows)+10);top.legend(loc='upper right');top.grid(alpha=.2)
for i,e in enumerate(events):
 x=e['time']-t0
 top.axvline(x,color='#777',alpha=.25)
 y=0 if e['component']=='api' else 1
 bottom.scatter(x,y,c='#3066be' if y==0 else '#b05b16',s=35)
 bottom.annotate(e['ip'],(x,y),xytext=(0,8),textcoords='offset points',rotation=70,fontsize=7)
bottom.set_yticks([0,1],['API deleted','worker deleted']);bottom.set_ylim(-.4,2.1);bottom.set_xlabel('Seconds since first request (each point = deleted Pod IP)');bottom.grid(alpha=.2)
fail=sum(not r['ok'] for r in requests)+sum(not r['ok'] for r in internal)
fig.suptitle(f'Service continuity: {len(requests)} NodePort + {len(internal)} cluster DNS orders, {fail} failed, {len(events)} pod deletions\nFresh TCP connection per request; no retries',fontsize=15)
fig.tight_layout();a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output,dpi=150)
summary={'start_utc':datetime.datetime.fromtimestamp(t0,datetime.timezone.utc).isoformat(),'requests':len(requests),'internal_requests':len(internal),'internal_failed':sum(not r['ok'] for r in internal),'max_start_gap_seconds':max(gaps),'failed':fail,'deleted_pods':len(events),'unique_deleted_ips':len({e['ip'] for e in events}),'windows':windows,'events':events}
a.output.with_suffix('.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ['windows','events']}))

if fail or len(requests)!=1800 or len(internal)!=1800: raise SystemExit("FAIL: incomplete run or failed requests")
