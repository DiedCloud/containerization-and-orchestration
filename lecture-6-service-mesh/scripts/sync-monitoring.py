"""Load this chart's CRs into the standalone Lab 2 Prometheus Helm release.
No Operator runs on this stand; preserve all other labs' scrape jobs/rules.
"""
import json,re,subprocess,tempfile
from pathlib import Path

def run(args): return subprocess.check_output(args,text=True)
def kube(*args): return json.loads(run(['kubectl',*args,'-o','json']))
mon=kube('-n','shop6','get','servicemonitor','shop-mesh')['spec']
rules=kube('-n','shop6','get','prometheusrule','shop-mesh')['spec']['groups']
values=json.loads(run(['helm','get','values','prometheus','-n','monitoring','-o','json']))
configs=values.get('extraScrapeConfigs','')
marker='# BEGIN shop6-mesh'
configs=re.sub(r'\n?# BEGIN shop6-mesh\n- [^\n]*(?:\n# END shop6-mesh)?\n?', '\n', configs).rstrip()+'\n'
relabels=[]
for key,val in mon['selector']['matchLabels'].items():
    import re
    relabels.append({'source_labels':['__meta_kubernetes_service_label_'+re.sub('[^A-Za-z0-9_]','_',key)],'action':'keep','regex':val})
relabels += [
 {'source_labels':['__meta_kubernetes_endpoint_port_name'],'action':'keep','regex':mon['endpoints'][0]['port']},
 {'source_labels':['__meta_kubernetes_endpoint_ready'],'action':'keep','regex':'true'},
 {'source_labels':['__meta_kubernetes_namespace'],'target_label':'namespace'},
 {'source_labels':['__meta_kubernetes_pod_name'],'target_label':'pod'},
 {'source_labels':['__meta_kubernetes_pod_label_deployment'],'target_label':'deployment'},
 {'source_labels':['__meta_kubernetes_pod_label_version'],'target_label':'version'}]
job={'job_name':'shop6-mesh','scrape_interval':mon['endpoints'][0]['interval'],
     'kubernetes_sd_configs':[{'role':'endpoints','namespaces':{'names':mon['namespaceSelector']['matchNames']}}],
     'relabel_configs':relabels}
old=values.get('serverFiles',{}).get('alerting_rules.yml',{}).get('groups',[])
merged=[g for g in old if g['name']!='shop6-mesh']+rules
override={'extraScrapeConfigs':configs+marker+'\n- '+json.dumps(job)+'\n# END shop6-mesh\n',
          'serverFiles':{'alerting_rules.yml':{'groups':merged}}}
check=subprocess.run(['kubectl','-n','monitoring','exec','-i','deploy/prometheus-server','-c','prometheus-server','--','promtool','check','rules','/dev/stdin'],input=json.dumps({'groups':rules}),text=True,check=True)
with tempfile.NamedTemporaryFile(mode='w',suffix='.json') as f:
    json.dump(override,f);f.flush()
    subprocess.run(['helm','upgrade','prometheus','prometheus-community/prometheus','--version','29.38.1','-n','monitoring','--reuse-values','-f',f.name,'--wait','--timeout','4m'],check=True)
print('Loaded shop6 ServiceMonitor and 3 alerts; other lab jobs retained')
