import base64,json,os,time,urllib.error,urllib.parse,urllib.request
REPO=os.environ.get('GITHUB_REPOSITORY','TanTzeHerng/chess.com-puzzles')
BRANCH=os.environ.get('DELTA_BRANCH','experiment/delta1-full-grading-20261027')
TOKEN=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN','')
SHAS={}
def api(path,data=None,method=None,raw=False):
 req=urllib.request.Request('https://api.github.com/repos/'+REPO+'/'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/vnd.github+json','User-Agent':'Delta1FullGrader','Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(req,timeout=30) as r:return r.read() if raw else json.load(r)
def publish(shard,record):
 path='delta1_benchmark/progress/shard-'+str(shard)+'.json';uri='contents/'+path
 for retry in range(5):
  try:
   if path not in SHAS:
    try:SHAS[path]=api(uri+'?ref='+urllib.parse.quote(BRANCH,safe=''))['sha']
    except urllib.error.HTTPError as e:
     if e.code!=404:raise
     SHAS[path]=None
   body={'message':'Delta-1 shard '+str(shard)+': '+str(len(record['results']))+' fully graded results [skip ci]','branch':BRANCH,'content':base64.b64encode(json.dumps(record,separators=(',',':')).encode()).decode()}
   if SHAS[path]:body['sha']=SHAS[path]
   answer=api(uri,body,'PUT');SHAS[path]=answer['content']['sha'];return
  except urllib.error.HTTPError as e:
   if e.code not in (409,422) or retry==4:raise
   SHAS.pop(path,None);time.sleep(1+retry)
def restore(shard,dest):
 import io,zipfile
 name='delta1-full-checkpoint-v1-s'+str(shard)
 for page in range(1,6):
  items=api('actions/artifacts?per_page=100&page='+str(page))['artifacts']
  for a in items:
   if a['name']==name and not a['expired']:
    payload=api('actions/artifacts/'+str(a['id'])+'/zip',raw=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
     for n in z.namelist():
      p=dest/n
      if not p.resolve().is_relative_to(dest.resolve()):raise ValueError('Unsafe checkpoint path')
     z.extractall(dest)
    print('RESTORED',a['id'],flush=True);return
  if len(items)<100:return
if __name__=='__main__':
 import sys
 from pathlib import Path
 restore(int(sys.argv[1]),Path(sys.argv[2]))
