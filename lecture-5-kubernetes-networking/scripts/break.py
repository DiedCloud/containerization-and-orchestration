"""Apply one randomly chosen Helm override; do not reveal it before diagnosis."""
import json
from pathlib import Path
import random
import subprocess

root = Path(__file__).resolve().parents[1]
variants = [
    {'networkPolicy': {'apiLabels': {'app.kubernetes.io/name': 'api-wrong'}}},
    {'networkPolicy': {'databasePort': 5433}},
    {'networkPolicy': {'dnsEnabled': False}},
    {'networkPolicy': {'postgresLabels': {'cnpg.io/cluster': 'wrong-cluster'}}},
]
override = random.choice(variants)
path = root/'results'/'fault-values.yaml'
path.parent.mkdir(exist_ok=True)
# JSON is valid YAML; this is an ordinary Helm values override.
path.write_text(json.dumps(override, indent=2)+'\n')
subprocess.run(['bash',str(root/'scripts'/'upgrade.sh'),'-f',str(path)],check=True,stdout=subprocess.DEVNULL)
print('Поломка применена. Начать с POST /order, затем посмотреть Hubble DROPPED.')
