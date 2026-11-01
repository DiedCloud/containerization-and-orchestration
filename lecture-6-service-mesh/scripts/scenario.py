"""Record HTTPRoute weights while an independent gate Job controls the rollout."""
import argparse,json,subprocess,time
from pathlib import Path
from prom import series
p=argparse.ArgumentParser();p.add_argument('name',choices=['bad','good']);a=p.parse_args()
r=Path(__file__).resolve().parents[1]
start=time.time();weights=[]
while time.time()-start < 480:
    route=json.loads(subprocess.check_output(['kubectl','-n','shop6','get','httproute','shop-api','-o','json']))
    weight=route['spec']['rules'][0]['backendRefs'][1]['weight']
    weights.append({'time':time.time(),'weight':weight})
    if weight in [0,100]:
        # Show post-decision traffic as well, allowing the 30s range to clear.
        time.sleep(40)
        weights.append({'time':time.time(),'weight':weight});break
    time.sleep(3)
else: raise RuntimeError('Gate did not converge')
end=time.time()
gate=[]
for line in subprocess.check_output(['kubectl','-n','shop6','logs','job/shop-gate'],text=True).splitlines():
    gate.append(json.loads(line))
sel='namespace="shop6",direction="inbound",target_port="8000",route_name!="probe"'
v2=sel+',deployment="shop-api-v2"'
error=f'(sum(rate(response_total{{{v2},status_code=~"5.."}}[30s])) or vector(0)) / sum(rate(response_total{{{v2}}}[30s]))'
traffic=f'sum(rate(response_total{{{v2}}}[30s])) / sum(rate(response_total{{{sel},deployment=~"shop-api-v[12]"}}[30s]))'
result={'start':start,'end':end,'weights':weights,'gate':gate,'error':series(error,start+30,end),'traffic':series(traffic,start+30,end)}
rows=[json.loads(x) for x in Path(f'/tmp/lab6-{a.name}-load.jsonl').read_text().splitlines()]
result['client']={'requests':len(rows),'http_errors':sum(x['code']!=201 for x in rows),
                  'transport_errors':sum(x['code']==0 for x in rows),
                  'max_start_gap_seconds':max(y['time']-y['ms']/1000-x['time']+x['ms']/1000 for x,y in zip(rows,rows[1:]))}
assert result['client']['transport_errors']==0 and result['client']['max_start_gap_seconds'] < 1
(r/f'evidence/{a.name}.json').write_text(json.dumps(result,indent=2))
assert weights[-1]['weight']==(0 if a.name=='bad' else 100)
print(json.dumps(gate,indent=2));print('Final weight:',weight)
