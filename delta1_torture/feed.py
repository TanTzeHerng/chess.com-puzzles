"""Independent GitHub progress channel for Puzzle Torture (no original feed writes)."""
import base64,json,os,time,urllib.parse,urllib.request,urllib.error
REPO=os.environ.get('GITHUB_REPOSITORY','TanTzeHerng/chess.com-puzzles')
BRANCH='experiment/delta1-puzzle-torture-20261028'
TOKEN=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN','')
SHAS={}
def request(uri,payload=None,method=None):
 headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/vnd.github+json',
  'User-Agent':'Delta1PuzzleTorture','Content-Type':'application/json'}
 req=urllib.request.Request('https://api.github.com/repos/'+REPO+'/'+uri,
  headers=headers,data=json.dumps(payload).encode() if payload is not None else None,method=method)
 with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
def publish(shard,record):
 path='delta1_torture/progress/shard-'+str(shard)+'.json'
 uri='contents/'+path
 for k in range(6):
  try:
   if path not in SHAS:
    try:SHAS[path]=request(uri+'?ref='+urllib.parse.quote(BRANCH,safe=''))['sha']
    except urllib.error.HTTPError as ex:
     if ex.code!=404:raise
     SHAS[path]=None
   body={'message':'[skip ci] Puzzle Torture live progress shard '+str(shard),
    'branch':BRANCH,'content':base64.b64encode(json.dumps(record,separators=(',',':')).encode()).decode()}
   if SHAS[path]:body['sha']=SHAS[path]
   result=request(uri,body,'PUT')
   SHAS[path]=result['content']['sha']
   return
  except urllib.error.HTTPError as e:
   if e.code not in (409,422) or k>=5:raise
   SHAS.pop(path,None);time.sleep(1+k)
