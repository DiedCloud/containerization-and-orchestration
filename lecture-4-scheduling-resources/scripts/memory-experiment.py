"""Observe real kubelet eviction at a bounded, documented lab threshold."""
import json
from pathlib import Path
import subprocess
import time
root=Path(__file__).resolve().parents[1]

def run(*args):
    return subprocess.check_output(args,text=True)
def kube(*args):
    return json.loads(run('kubectl','--context','kind-lab2',*args,'-o','json'))
def fingerprint(pods):
    return {p['metadata']['name']:{'uid':p['metadata']['uid'],'qos':p['status'].get('qosClass'),
            'phase':p['status']['phase'],'node':p['spec'].get('nodeName'),
            'restarts':sum(c['restartCount'] for c in p['status'].get('containerStatuses',[]))}
            for p in pods if p['metadata']['labels'].get('app.kubernetes.io/name') in ['api','postgres']}

before=kube('-n','shop','get','pods')['items']
stats=json.loads(run('kubectl','get','--raw','/api/v1/nodes/lab2-worker/proxy/stats/summary'))
available=stats['node']['memory']['availableBytes']
threshold=int(available/1048576)-384
record={'baseline_memory':stats['node']['memory'],'threshold_mi':threshold,
        'critical_before':fingerprint(before),'samples':[]}
path=root/'evidence/07-memory-observation.json'
try:
    subprocess.run(['python3',str(root/'scripts/node-resources.py'),'--memory-threshold',str(threshold)+'Mi'],check=True)
    subprocess.run(['python3',str(root/'scripts/mark.py'),'memory-pressure-start'],check=True)
    subprocess.run(['bash',str(root/'scripts/upgrade.sh'),'-f',str(root/'experiments/07-memory.yaml')],check=True)
    deadline=time.monotonic()+180
    saw_pressure=saw_evicted=False
    while time.monotonic()<deadline:
        pods=kube('-n','shop','get','pods')['items']
        node=kube('get','node','lab2-worker')
        pressure=next(c['status'] for c in node['status']['conditions'] if c['type']=='MemoryPressure')
        evicted=[p for p in pods if p['status'].get('reason')=='Evicted']
        record['samples'].append({'time':time.time(),'memory_pressure':pressure,'evicted':[p['metadata']['name'] for p in evicted]})
        if pressure=='True' and not saw_pressure:
            (root/'evidence/07-pressure-node.json').write_text(json.dumps(node,indent=2)+'\n')
            subprocess.run(['python3',str(root/'scripts/observe.py'),'07-pressure'],check=True)
            print('MemoryPressure=True observed',flush=True)
            saw_pressure=True
        if evicted and not saw_evicted:
            (root/'evidence/07-evicted-pods.json').write_text(json.dumps(evicted,indent=2)+'\n')
            subprocess.run(['python3',str(root/'scripts/observe.py'),'07-eviction'],check=True)
            record['critical_after']=fingerprint(pods)
            print('Evicted:',[p['metadata']['name'] for p in evicted],flush=True)
            saw_evicted=True
        path.write_text(json.dumps(record,indent=2)+'\n')
        if saw_pressure and saw_evicted:
            # Hold the experiment long enough to expose metrics/pressure cycles.
            if time.monotonic()>deadline-90:
                break
        time.sleep(2)
    if not saw_evicted:raise RuntimeError('No kubelet eviction observed')
    record['critical_after']=fingerprint(kube('-n','shop','get','pods')['items'])
    record['saw_memory_pressure']=saw_pressure
    record['saw_evicted']=saw_evicted
    path.write_text(json.dumps(record,indent=2)+'\n')
finally:
    subprocess.run(['python3',str(root/'scripts/node-resources.py'),'--memory-threshold','100Mi'],check=True)
    subprocess.run(['bash',str(root/'scripts/upgrade.sh'),'--wait','--timeout','3m'],check=True)
    subprocess.run(['python3',str(root/'scripts/mark.py'),'memory-pressure-end'],check=True)
