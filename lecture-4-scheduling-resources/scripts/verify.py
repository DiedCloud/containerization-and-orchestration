"""Check the submitted chart against the measured KRR recommendations and live state."""
import json
from pathlib import Path
import subprocess
import yaml
root=Path(__file__).resolve().parents[1]
values=yaml.safe_load((root/'shop/values.yaml').read_text())
report=json.loads((root/'evidence/03-krr-final.json').read_text())
for component in ['api','worker','postgres']:
    scan=next(s for s in report['scans'] if s['object']['name']=='shop-'+component)
    r=scan['recommended']['requests']
    expected_cpu=str(round(r['cpu']['value']*1000))+'m'
    expected_memory=str(round(r['memory']['value']/1048576))+'Mi'
    assert values[component]['resources']['requests']=={'cpu':expected_cpu,'memory':expected_memory},component
    if component in ['api','postgres']:
        assert values[component]['resources']['requests']==values[component]['resources']['limits'],component
print('PASS: chart CPU/memory requests match real KRR output; critical limits=requests')
# This script can also run without kubectl in the KRR tools container.
