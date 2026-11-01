"""Permit the mesh infrastructure and its official images, retain application checks."""
import json
import subprocess
policy=json.loads(subprocess.check_output(['kubectl','get','clusterpolicy','platform-guardrails','-o','json']))
rules=policy['spec']['rules']
for rule in rules:
    namespaces=rule['exclude']['any'][0]['resources']['namespaces']
    if 'linkerd' not in namespaces:
        namespaces.append('linkerd')
    if rule['name']=='trusted-image-sources':
        condition=rule['validate']['foreach'][0]['deny']['conditions']['any'][0]
        condition['key']=condition['key'].replace('ghcr.io/cloudnative-pg/[^/]+)', 'ghcr.io/cloudnative-pg/[^/]+|cr.l5d.io/linkerd/[^/]+)')
subprocess.run(['kubectl','patch','clusterpolicy','platform-guardrails','--type=merge','-p',json.dumps({'spec':{'rules':rules}})],check=True)
