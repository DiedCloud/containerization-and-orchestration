"""Kubernetes 1.37: allow preloaded local lab images without registry verification."""
import json,re,subprocess
for node in subprocess.check_output(['kind','get','nodes','--name','lab2'],text=True).split():
    path='/var/lib/kubelet/config.yaml'
    config=subprocess.check_output(['docker','exec',node,'cat',path],text=True)
    match=re.search(r'^preloadedImagesVerificationAllowlist: (.*)$',config,re.M)
    allowed=set(json.loads(match[1]) if match else [])
    wanted={'docker.io/library/shop','docker.io/library/shop-gate'}
    if wanted <= allowed:
        continue
    allowed.update(wanted)
    config=re.sub(r'^preloadedImagesVerificationAllowlist:.*\n?','',config,flags=re.M)
    config += '\npreloadedImagesVerificationAllowlist: '+json.dumps(sorted(allowed))+'\n'
    subprocess.run(['docker','exec','-i',node,'tee',path],input=config,text=True,stdout=subprocess.DEVNULL,check=True)
    subprocess.run(['docker','exec',node,'systemctl','restart','kubelet'],check=True)
