"""Check live proxy scrapes, alert definitions, dashboard queries and completed release."""
import base64,json,subprocess,urllib.request
from pathlib import Path
from prom import query
r=Path(__file__).resolve().parents[1]
def kube(*args): return json.loads(subprocess.check_output(['kubectl',*args,'-o','json']))
expected=json.loads((r/'shop/dashboards/mesh.json').read_text())
secret=kube('-n','monitoring','get','secret','grafana')['data']
auth=base64.b64encode(base64.b64decode(secret['admin-user'])+b':'+base64.b64decode(secret['admin-password'])).decode()
req=urllib.request.Request('http://localhost:13000/api/dashboards/uid/shop6-mesh',headers={'Authorization':'Basic '+auth})
d=json.load(urllib.request.urlopen(req))
assert d['meta']['provisioned'] and d['dashboard']['panels']==expected['panels']
queries=[]
for panel in expected['panels']:
    for target in panel['targets']:
        # Range functions may have no samples once the load stops; successful evaluation is required.
        data=query(target['expr'])
        queries.append({'panel':panel['title'],'ref':target['refId'],'series':len(data)})
targets=query('up{job="shop6-mesh"}')
assert len(targets)==4 and all(float(t['value'][1])==1 for t in targets)
groups=json.load(urllib.request.urlopen('http://localhost:19090/api/v1/rules'))['data']['groups']
rules=[x for g in groups if g['name']=='shop6-mesh' for x in g['rules']]
assert len(rules)==3 and all(x['health']=='ok' for x in rules)
weight=kube('-n','shop6','get','httproute','shop-api')['spec']['rules'][0]['backendRefs'][1]['weight']
assert weight==100
job=kube('-n','shop6','get','job','shop-gate')
assert job['status'].get('succeeded')==1
versions=subprocess.check_output(['kubectl','-n','shop6','exec','deploy/shop-client','-c','client','--','python','-c',
 'import urllib.request,json; print(json.dumps([urllib.request.urlopen("http://shop-api:8000/version").read().decode() for _ in range(30)]))'],text=True)
assert json.loads(versions)==['v2']*30
old=json.loads((r/'evidence/monitoring.json').read_text())
observed=old.get('observedCanaryErrorsFiring') or any(x['metric'].get('alertname')=='CanaryErrors' and x['metric'].get('alertstate')=='firing' for x in old.get('alerts',[]))
assert observed
result={'targets':[{'pod':x['metric']['pod'],'up':float(x['value'][1])} for x in targets],
        'rules':[{'name':x['name'],'health':x['health'],'state':x['state']} for x in rules],
        'observedCanaryErrorsFiring':observed,'dashboard':{'uid':expected['uid'],'provisioned':True,'panels':len(expected['panels'])},
        'queries':queries,'finalV2Weight':weight,'gateCompleted':True,'versionCheck':'30/30 v2'}
(r/'evidence/monitoring.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
