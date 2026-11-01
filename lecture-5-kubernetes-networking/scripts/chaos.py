"""Delete a random api/worker pod every few seconds, recording actual identities."""
import argparse
import json
import random
import subprocess
import time
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--duration', type=int, default=180)
p.add_argument('--interval', type=float, default=7)
p.add_argument('--output', type=Path, default=Path('results/chaos.jsonl'))
a = p.parse_args()
a.output.parent.mkdir(parents=True, exist_ok=True)
end = time.monotonic() + a.duration
with a.output.open('w') as out:
    while time.monotonic() < end:
        pods = json.loads(subprocess.check_output(['kubectl', '-n', 'shop', 'get', 'pods', '-l',
            'app.kubernetes.io/name in (api,worker)', '-o', 'json']))['items']
        ready = [x for x in pods if not x['metadata'].get('deletionTimestamp') and
                 any(c['type'] == 'Ready' and c['status'] == 'True' for c in x['status'].get('conditions', []))]
        # Only one deletion at a time; retain at least one Ready API/worker.
        candidates = [x for x in ready if sum(y['metadata']['labels']['app.kubernetes.io/name'] ==
                      x['metadata']['labels']['app.kubernetes.io/name'] for y in ready) >= 2]
        if candidates:
            pod = random.choice(candidates)
            event = {'time': time.time(), 'pod': pod['metadata']['name'],
                     'uid': pod['metadata']['uid'], 'ip': pod['status']['podIP'],
                     'component': pod['metadata']['labels']['app.kubernetes.io/name']}
            subprocess.run(['kubectl', '-n', 'shop', 'delete', 'pod', event['pod'], '--wait=false'], check=True)
            out.write(json.dumps(event) + '\n'); out.flush()
        time.sleep(a.interval)
