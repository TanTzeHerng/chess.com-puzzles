import pathlib,subprocess,sys,urllib.request,json
ROOT=pathlib.Path(__file__).resolve().parent
try:
 with urllib.request.urlopen('http://127.0.0.1:8767/health.json',timeout=3) as r:d=json.load(r)
 if d.get('relay_version')!='delta1-auto-v1':raise RuntimeError('Old dashboard server')
except Exception:
 subprocess.Popen([str(pathlib.Path(sys.executable).with_name('pythonw.exe')),str(ROOT/'pc_relay.py')],cwd=ROOT,creationflags=0x08000000,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
