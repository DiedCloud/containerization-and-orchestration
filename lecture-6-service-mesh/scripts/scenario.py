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
result={'start':start,'end':end,'weights':weights,'gate':gate,'error':series(error,start,end),'traffic':series(traffic,start,end)}
(r/f'evidence/{a.name}.json').write_text(json.dumps(result,indent=2))
assert weights[-1]['weight']==(0 if a.name=='bad' else 100)
print(json.dumps(gate,indent=2));print('Final weight:',weight)
