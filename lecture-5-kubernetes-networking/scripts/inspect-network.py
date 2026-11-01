"""Show a Pod's eth0, the peer veth on its node and a cross-node request."""
import json
import subprocess

def run(*cmd):
    print('$ '+' '.join(cmd), flush=True)
    value=subprocess.check_output(cmd,text=True)
    print(value.strip(),flush=True)
    return value
pods=json.loads(subprocess.check_output(['kubectl','-n','shop','get','pods','-l','app.kubernetes.io/name=api','-o','json']))['items']
pods=[p for p in pods if not p['metadata'].get('deletionTimestamp')]
a=pods[0];b=next(p for p in pods if p['spec']['nodeName']!=a['spec']['nodeName'])
name=a['metadata']['name'];node=a['spec']['nodeName']
run('kubectl','-n','shop','get','pods','-o','wide')
code='''import socket,fcntl,struct,pathlib
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
print("eth0 IP:",socket.inet_ntoa(fcntl.ioctl(s.fileno(),0x8915,struct.pack("256s",b"eth0"))[20:24]))
for key in ["ifindex","iflink","address","mtu"]:
 print("eth0",key,pathlib.Path("/sys/class/net/eth0/"+key).read_text().strip())'''
run('kubectl','-n','shop','exec',name,'--','python','-c',code)
peer=subprocess.check_output(['kubectl','-n','shop','exec',name,'--','cat','/sys/class/net/eth0/iflink'],text=True).strip()
links=json.loads(subprocess.check_output(['docker','exec',node,'ip','-j','link']))
veth=next(link['ifname'] for link in links if str(link['ifindex'])==peer)
run('docker','exec',node,'ip','-d','link','show',veth)
run('docker','exec',node,'ip','route','get',b['status']['podIP'])
print('Direct cross-node request:',node,'->',b['spec']['nodeName'],flush=True)
run('kubectl','-n','shop','exec',name,'--','python','-c',
    f'import urllib.request;print(urllib.request.urlopen("http://{b["status"]["podIP"]}:8000/health",timeout=3).read().decode())')
config=json.loads(subprocess.check_output(['kubectl','-n','kube-system','get','configmap','kube-proxy','-o','json']))['data']['config.conf']
print('\n$ kubectl -n kube-system get configmap kube-proxy: selected mode')
print(next(line for line in config.splitlines() if line.startswith('mode:')))
