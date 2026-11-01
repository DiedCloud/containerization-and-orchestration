"""Add the chart's dashboard to the existing Grafana file provisioning."""
import json,subprocess,tempfile
v=json.loads(subprocess.check_output(['helm','get','values','grafana','-n','monitoring','-o','json']))
providers=v['dashboardProviders']['dashboardproviders.yaml']
providers['providers']=[p for p in providers['providers'] if p['name']!='shop6']+[
 {'name':'shop6','orgId':1,'folder':'Labs','type':'file','disableDeletion':False,'allowUiUpdates':False,'options':{'path':'/var/lib/grafana/dashboards/shop6'}}]
maps=v.get('dashboardsConfigMaps',{});maps['shop6']='shop6-dashboard'
with tempfile.NamedTemporaryFile(mode='w',suffix='.json') as f:
 json.dump({'dashboardProviders':{'dashboardproviders.yaml':providers},'dashboardsConfigMaps':maps},f);f.flush()
 subprocess.run(['helm','upgrade','grafana','grafana/grafana','--version','10.5.15','-n','monitoring','--reuse-values','-f',f.name,'--wait','--timeout','4m'],check=True)
