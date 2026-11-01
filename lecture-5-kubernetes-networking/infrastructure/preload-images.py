"""Preload Cilium on kind nodes when registry access from nodes is unavailable."""
from pathlib import Path
import concurrent.futures
import re
import json
import subprocess

root = Path(__file__).resolve().parent
rendered = subprocess.check_output(['helm','template','cilium','cilium/cilium','--version','1.20.4',
    '-n','kube-system','-f',str(root/'cilium-values.yaml')],text=True)
images = sorted(set(re.findall(r'image: "([^"]+)"',rendered)))
def load(image):
    subprocess.run(['docker','pull',image],check=True)
    subprocess.run(['kind','load','docker-image','--name','lab2',image],check=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(load,images))
# Kubernetes 1.37 remembers failed pull attempts even after a manual import.
# Exempt only these public Cilium images from credential reverification.
for node in subprocess.check_output(['kind','get','nodes','--name','lab2'],text=True).split():
    config = subprocess.check_output(['docker','exec',node,'cat','/var/lib/kubelet/config.yaml'],text=True)
    config = re.sub(r'^imagePullCredentialsVerificationPolicy:.*\n','',config,flags=re.M)
    # Preserve access to the existing preloaded Lab 2/3 infrastructure too.
    images = json.loads(subprocess.check_output(['docker','exec',node,'crictl','images','-o','json']))['images']
    repositories = sorted({tag.rsplit(':',1)[0] for image in images for tag in image.get('repoTags',[])})
    config = re.sub(r'^preloadedImagesVerificationAllowlist:.*\n','',config,flags=re.M)
    config += '\nimagePullCredentialsVerificationPolicy: NeverVerifyAllowlistedImages\npreloadedImagesVerificationAllowlist: ' + json.dumps(repositories) + '\n'
    subprocess.run(['docker','exec','-i',node,'tee','/var/lib/kubelet/config.yaml'],input=config,text=True,
                   stdout=subprocess.DEVNULL,check=True)
    subprocess.run(['docker','exec',node,'systemctl','restart','kubelet'],check=True)
