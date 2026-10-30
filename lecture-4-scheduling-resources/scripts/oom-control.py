"""Separate cgroup OOM control after restoring the ordinary eviction threshold."""
import json
from pathlib import Path
import subprocess
import time
root=Path(__file__).resolve().parents[1]
subprocess.run(['bash',str(root/'scripts/upgrade.sh'),'-f',str(root/'experiments/07-oom-control.yaml')],check=True)
for _ in range(90):
    pods=json.loads(subprocess.check_output(['kubectl','-n','shop','get','pods','-l','app=shop-batch','-o','json']))['items']
    matches=[p for p in pods if any(c.get('lastState',{}).get('terminated',{}).get('reason')=='OOMKilled' for c in p['status'].get('containerStatuses',[]))]
    if matches:
        (root/'evidence/07-oom-pod.json').write_text(json.dumps(matches,indent=2)+'\n')
        p=root/'evidence/07-oom-control.txt'
        with p.open('w') as out:
            out.write('Actual cgroup OOM control; memory eviction threshold restored to 100Mi\n')
            for pod in matches:
                out.write(json.dumps({'name':pod['metadata']['name'],'qos':pod['status']['qosClass'],'resources':pod['spec']['containers'][0]['resources'],'status':pod['status']['containerStatuses']},indent=2)+'\n')
        break
    time.sleep(1)
else:raise RuntimeError('OOMKilled not observed')
subprocess.run(['bash',str(root/'scripts/upgrade.sh'),'--wait','--timeout','3m'],check=True)
print('OOMKilled control captured; default batch profile restored')
