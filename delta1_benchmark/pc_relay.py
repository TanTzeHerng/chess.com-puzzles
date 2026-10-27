"""Display-only PC relay. All Delta-1 engines and grading stay in cloud."""
import base64,datetime as dt,json,math,os,pathlib,subprocess,threading,time,urllib.parse,urllib.request
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
ROOT=pathlib.Path(__file__).resolve().parent
BRANCH='experiment/delta1-2500plus-999999-20261027';REPO='TanTzeHerng/chess.com-puzzles'
GH=r'C:\Program Files\GitHub CLI\gh.exe';TOKEN=None;POLL=10;LAST_GOOD={};FETCH_ERROR=None
CREATE_NO_WINDOW=0x08000000
def utc():return dt.datetime.now(dt.timezone.utc).isoformat()
def age(s):return max(0,(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(s.replace('Z','+00:00'))).total_seconds())
def write(path,obj):
 for n in range(5):
  p=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
  try:p.write_text(json.dumps(obj,separators=(',',':')),encoding='utf8');os.replace(p,path);return
  except PermissionError:time.sleep(.05*(n+1))
 raise RuntimeError('Dashboard file is locked')
def token():
 global TOKEN
 if TOKEN is None:
  try:TOKEN=subprocess.check_output([GH,'auth','token'],text=True,creationflags=CREATE_NO_WINDOW,stderr=subprocess.DEVNULL,timeout=15).strip()
  except Exception:TOKEN=''
 return TOKEN
def fetch(shard):
 path='delta1_benchmark/progress/shard-'+str(shard)+'.json';url='https://api.github.com/repos/'+REPO+'/contents/'+path+'?ref='+urllib.parse.quote(BRANCH,safe='')+'&_='+str(time.time_ns())
 headers={'User-Agent':'Delta1PCDashboard','Accept':'application/vnd.github.raw+json','Cache-Control':'no-cache'}
 if token():headers['Authorization']='Bearer '+token()
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=12) as r:d=json.load(r)
  if 'content' in d:d=json.loads(base64.b64decode(d['content']))
 except Exception:
  url='https://raw.githubusercontent.com/'+REPO+'/'+BRANCH+'/'+path+'?_='+str(time.time_ns())
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Delta1PCDashboard','Cache-Control':'no-cache'}),timeout=12) as r:d=json.load(r)
 if d.get('schema')!=2 or d.get('level')!='999999':raise ValueError('Wrong Delta feed schema/level')
 if d['shard']!=shard:raise ValueError('Wrong shard identity')
 return d
def aggregate(parts):
 live=[];stale=[];recent=[];bins={};counts={k:0 for k in ['solved','missed','technical','retry_waiting','technical_attempts','attempted_unique','queued']}
 for shard,d in parts.items():
  if d.get('epoch')!='20261027T090152Z':raise ValueError('Old run epoch rejected')
  if age(d['heartbeat_utc'])>120 and d.get('state')!='completed':stale.append(shard)
  elif d.get('state')=='running':live+=list(d.get('active',{}).values())
  for k in counts:counts[k]+=d.get('counts',{}).get(k,0)
  for rating,n in d.get('rating_bins',{}).items():
   z=bins.setdefault(rating,[0,0]);z[0]+=n[0];z[1]+=n[1]
  for r in d.get('recent',[]):
   if r.get('status')=='solved':
    if not(r.get('initial_rom_board_verified') and r.get('all_solver_positions_verified') and r.get('moves_matched')==r.get('moves_required')):raise ValueError('Incomplete solve rejected')
    if not all(x['actual']==x['expected'] and x['rom_board_verified'] for x in r['moves']):raise ValueError('Mismatched solve rejected')
   recent.append(r)
 ids=[x['id'] for x in live]
 if len(ids)!=len(set(ids)):raise ValueError('Duplicate active puzzle IDs')
 assert sum(n[0] for n in bins.values())==counts['solved']
 assert sum(n[1] for n in bins.values())==counts['missed']
 q=math.log(10)/400;information=0.;surprise=0.
 for rp,(wins,losses) in bins.items():
  n=wins+losses;e=1/(1+10**((int(rp)-2000)/400));information+=q*q*n*e*(1-e);surprise+=wins-n*e
 inv=1/(350*350)+information;rating=2000+q/inv*surprise;rd=math.sqrt(1/inv)
 complete=len(parts)==4 and all(d.get('state')=='completed' for d in parts.values());counts['running']=len(live)
 state='COMPLETED' if complete else 'STALE OR PARTIAL CLOUD FEED' if stale or len(parts)<4 else 'SEARCHING AND GRADING AUTOMATICALLY' if live else 'CLOUD WORKERS STARTING'
 last_update=min((d['heartbeat_utc'] for d in parts.values() if d.get('state')!='completed'),default=max((d['heartbeat_utc'] for d in parts.values()),default=utc()))
 eligible=max((d.get('eligible',0) for d in parts.values()),default=0)
 trend=[]
 try:
  previous=json.loads((ROOT/'status.json').read_text(encoding='utf8'))
  if previous.get('epoch')=='20261027T090152Z':trend=previous.get('trend',[])
 except Exception:pass
 if not trend or trend[-1].get('utc')!=last_update:trend.append({'utc':last_update,'rating':rating})
 return {'epoch':'20261027T090152Z','engine':'Novag Chess Champion Delta-1','level':'999999','min_puzzle_rating':2500,'max_puzzle_rating':None,'rating':rating,'rd':rd,'initial_rating':2000,'initial_rd':350,'rated':counts['solved']+counts['missed'],'max_logical_workers':256,'actual_running_workers':len(live),'counts':counts,'eligible':eligible,'recent':[{'id':r['id'],'rating':r['rating'],'score':r['score'],'after_rating':rating,'moves_matched':r.get('moves_matched'),'moves_required':r.get('moves_required')} for r in sorted(recent,key=lambda r:r.get('finished_at',''),reverse=True)[:40]],'trend':trend[-1000:],'state':state,'last_update':last_update,'shards_reporting':len(parts),'stale_shards':stale,'complete':complete,'message':'Level 999999; all available Chess.com puzzles rated 2500+. A free worker immediately takes another puzzle. Every technical error is queued for retry, unscored. All solver moves and ROM board squares must verify. Glicko-1 is recalculated over this run as one rating period against fixed puzzle ratings.'}
def loop():
 global FETCH_ERROR
 from concurrent.futures import ThreadPoolExecutor,as_completed
 with ThreadPoolExecutor(max_workers=4) as pool:
  while True:
   began=time.monotonic();errs=[]
   jobs={pool.submit(fetch,i):i for i in range(4)}
   for f in as_completed(jobs):
    i=jobs[f]
    try:
     d=f.result()
     if i not in LAST_GOOD or d['heartbeat_utc']>=LAST_GOOD[i]['heartbeat_utc']:LAST_GOOD[i]=d
    except Exception as e:errs.append(str(i)+': '+repr(e))
   try:
    if LAST_GOOD:write(ROOT/'status.json',aggregate(LAST_GOOD))
    FETCH_ERROR='; '.join(errs) or None
    write(ROOT/'relay_health.json',{'pc_fetch_utc':utc(),'fetch_error':FETCH_ERROR,'shards':len(LAST_GOOD)})
   except Exception as e:FETCH_ERROR=repr(e)
   time.sleep(max(1,POLL-(time.monotonic()-began)))
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**k):super().__init__(*a,directory=str(ROOT),**k)
 def log_message(self,*a):pass
 def end_headers(self):self.send_header('Cache-Control','no-store, max-age=0');super().end_headers()
 def do_GET(self):
  path=urllib.parse.urlsplit(self.path).path
  if path=='/health.json':
   try:
    d=json.loads((ROOT/'status.json').read_text(encoding='utf8'));seconds=age(d['last_update']);fresh=(d.get('complete') or seconds<120) and d.get('shards_reporting')==4 and not d.get('stale_shards')
    data={'dashboard_server_utc':utc(),'dashboard_server_live':True,'relay_version':'delta1-auto-v1','remote_heartbeat_age_s':seconds,'remote_workers_reported':d.get('actual_running_workers',0),'remote_state':d['state'],'remote_feed_fresh':bool(fresh),'relay_error':FETCH_ERROR}
   except Exception as e:data={'dashboard_server_utc':utc(),'dashboard_server_live':True,'remote_feed_fresh':False,'remote_state':repr(e)}
   payload=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
  if path not in ('/','/index.html','/status.json','/relay_health.json'):self.send_error(404);return
  return super().do_GET()
if __name__=='__main__':
 threading.Thread(target=loop,daemon=True).start();ThreadingHTTPServer(('127.0.0.1',8767),Handler).serve_forever()
