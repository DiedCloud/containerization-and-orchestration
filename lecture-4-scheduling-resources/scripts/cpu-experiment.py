"""Fill CPU requests, record Pending/firing, then provoke real scheduler preemption."""
import json
from pathlib import Path
import subprocess
import time
root=Path(__file__).resolve().parents[1]
def run(*args):
    subprocess.run(args,check=True)
def pods():
    return json.loads(subprocess.check_output(['kubectl','-n','shop','get','pods','-o','json']))['items']
run('python3',str(root/'scripts/experiment-capacity.py'))
run('python3',str(root/'scripts/mark.py'),'cpu-fill-start')
run('bash',str(root/'scripts/upgrade.sh'),'-f',str(root/'experiments/06-fill.yaml'))
for _ in range(60):
    current=pods()
    pending=[p for p in current if p['metadata']['labels'].get('app')=='shop-batch' and p['status']['phase']=='Pending']
    if pending:break
    time.sleep(1)
else:raise RuntimeError('No Pending batch observed')
run('python3',str(root/'scripts/observe.py'),'06-pending')
run('python3',str(root/'scripts/capture-alerts.py'),'ShopBatchUnschedulable')
run('python3',str(root/'scripts/mark.py'),'api-preemption-start')
run('bash',str(root/'scripts/upgrade.sh'),'-f',str(root/'experiments/06-fill.yaml'),'-f',str(root/'experiments/06-preemption.yaml'))
for _ in range(120):
    events=json.loads(subprocess.check_output(['kubectl','-n','shop','get','events','-o','json']))['items']
    victims=[e for e in events if e['reason']=='Preempted' and e['involvedObject']['name'].startswith('shop-batch-')]
    current=pods()
    ready_api=[p for p in current if p['metadata']['labels'].get('app.kubernetes.io/name')=='api' and not p['metadata'].get('deletionTimestamp') and all(c['ready'] for c in p['status'].get('containerStatuses',[])) and p['status'].get('containerStatuses')]
    if victims and len(ready_api)==4:
        (root/'evidence/06-preempted-events.json').write_text(json.dumps(victims,indent=2)+'\n')
        break
    time.sleep(1)
else:raise RuntimeError('Preemption or four healthy API replicas not observed')
run('python3',str(root/'scripts/observe.py'),'06-preemption')
print('Observed actual batch preemption and four healthy API replicas',flush=True)
# Keep an observable interval for graphs after preemption.
time.sleep(30)
run('bash',str(root/'scripts/restore-capacity.sh'))
run('bash',str(root/'scripts/upgrade.sh'),'--wait','--timeout','3m')
run('python3',str(root/'scripts/mark.py'),'cpu-pressure-end')
