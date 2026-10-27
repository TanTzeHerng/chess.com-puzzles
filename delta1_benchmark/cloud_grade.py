import argparse,asyncio,datetime,json,os,re,time,collections,heapq,gzip
from pathlib import Path
import chess
from github_feed import publish
ROOT=Path(__file__).resolve().parent
P=argparse.ArgumentParser();P.add_argument('--shard',type=int,required=True);P.add_argument('--shards',type=int,default=4);P.add_argument('--budget',type=int,default=19500);P.add_argument('--work',default='work');P.add_argument('--workers',type=int,default=64);A=P.parse_args()
assert 1<=A.workers<=64
WORK=Path(A.work).resolve();WORK.mkdir(parents=True,exist_ok=True)
ALL_ROWS=json.loads((ROOT/'sources.json').read_text());TOTAL=len(ALL_ROWS);ROWS=[r for r in ALL_ROWS if r['index']%A.shards==A.shard];BYID={r['id']:r for r in ROWS};EPOCH='20261027T090152Z'
START=time.monotonic();RESULTS={};ACTIVE={};PROCS={};STOP=False;TECHNICAL={};RETRY=[];NEW=collections.deque();INFLIGHT=set();ATTEMPTED=set()
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def atom(path,x):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(x,separators=(',',':')));temp.replace(path)
def bh(b):return bytes(((p.piece_type if p.color else -p.piece_type)&255) if (p:=b.piece_at(q)) else 0 for q in range(64)).hex()
def snapshot():
 live={k:v for k,v in ACTIVE.items() if k in PROCS and PROCS[k].returncode is None}
 result=sorted(RESULTS.values(),key=lambda r:r['index'])
 bins={}
 for r in result:
  z=bins.setdefault(str(r['rating']),[0,0]);z[0 if r['score']==1 else 1]+=1
 recent=sorted(result,key=lambda r:r['finished_at'],reverse=True)[:50]
 return {'schema':2,'epoch':EPOCH,'run_id':os.environ.get('GITHUB_RUN_ID','local'),'shard':A.shard,'heartbeat_utc':utc(),'level':'999999','initial_rating':2000,'initial_rd':350,'max_logical_workers':256,'actual_running_workers':len(live),'active':live,'eligible':TOTAL,'shard_eligible':len(ROWS),'recent':recent,'rating_bins':bins,'counts':{'solved':sum(r['status']=='solved' for r in result),'missed':sum(r['status']=='missed' for r in result),'technical':len(TECHNICAL),'retry_waiting':len(RETRY),'technical_attempts':sum(r.get('technical_attempts',1) for r in TECHNICAL.values()),'attempted_unique':len(ATTEMPTED),'running':len(live),'queued':len(NEW)},'queue_mode':'shared queue: free worker takes next puzzle immediately; technical errors automatically retried','state':'pausing' if STOP else 'completed' if len(result)==len(ROWS) else 'running','grading_rule':'All solver moves must match complete Chess.com line, with verified ROM boards; technical errors unscored.'}
def saved_result(row):
 path=WORK/(str(row['id'])+'_result.json')
 if path.exists():
  d=json.loads(path.read_text());return d if d.get('id')==row['id'] and d.get('status') in ('solved','missed') else None
 return None
def source_check(row):
 if 'source_error' in row:raise ValueError(row['source_error'])
 b=chess.Board(row['initialFen'])
 if not b.is_valid():raise ValueError('Invalid source FEN')
 if b.castling_rights or b.ep_square is not None:raise ValueError('Position rights not supported by verified keypad adapter')
 for color,k,rs in [(chess.WHITE,chess.E1,(chess.A1,chess.H1)),(chess.BLACK,chess.E8,(chess.A8,chess.H8))]:
  if b.king(color)==k and any(b.piece_at(s)==chess.Piece(chess.ROOK,color) for s in rs):raise ValueError('Original castling-history state is not independently reconstructible')
 for u in [row['setupMoveUci']]+row['solutionUci']:
  m=chess.Move.from_uci(u)
  if m not in b.legal_moves:raise ValueError('Incomplete/illegal source solution')
  if len(u)!=4:raise ValueError('Promotion input requires separately verified adapter')
  b.push(m)
async def run(row,slot):
 ident=row['id'];key=str(ident);engine=None;trace=None;attempt={'id':ident,'index':row['index'],'lane':row['lane'],'worker_id':A.shard*64+slot,'rating':row['rating'],'level':'999999','started_at':utc(),'status':'running','score':None,'moves':[],'moves_required':len(row.get('solutionUci',[])[::2]),'moves_matched':0,'initial_rom_board_verified':False}
 def log(kind,**kw):trace.write(json.dumps({'utc':utc(),'kind':kind,**kw})+'\n')
 async def send(s):log('send',command=s);engine.stdin.write((s+'\n').encode());await engine.stdin.drain()
 async def until(prefix):
  while True:
   raw=await engine.stdout.readline()
   if not raw:raise RuntimeError('Engine closed before '+prefix)
   s=raw.decode().strip();log('receive',text=s)
   if s.startswith('error '):raise RuntimeError(s)
   if s.startswith('info '):ACTIVE[key]['engine_info']=s;ACTIVE[key]['updated_at']=utc()
   if s.startswith('info completed_board_hex='):ACTIVE[key]['completed']=s
   if s.startswith(prefix):return s
 try:
  source_check(row);meta_path=WORK/(key+'_pending.json');meta=json.loads(meta_path.read_text()) if meta_path.exists() else None
  resume=bool(meta and (WORK/meta['checkpoint']).exists())
  trace=gzip.open(WORK/(key+'.jsonl.gz'),'at',encoding='utf8')
  engine=await asyncio.create_subprocess_exec(str(ROOT/'delta1_puzzle_engine'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT);PROCS[key]=engine
  ACTIVE[key]={'id':ident,'lane':row['lane'],'worker_id':A.shard*64+slot,'pid':engine.pid,'solver_moves_matched':0,'updated_at':utc(),'stage':'loading'}
  if resume:
   attempt=meta['attempt'];b=chess.Board(meta['fen']);start_i=meta['solver_ply'];await send('load '+str(WORK/meta['checkpoint']));await until('loaded checkpoint ')
  else:
   b=chess.Board(row['initialFen']);await send('setup '+row['initialFen']);ready=await until('ready ')
   if 'board_hex='+bh(b) not in ready or 'level=999999' not in ready:raise RuntimeError('Initial ROM board/level verification failed')
   color='white' if row['colorOfUser']=='white' else 'black'
   if 'computer_color='+color not in ready:raise RuntimeError('Wrong solver side')
   attempt['initial_rom_board_verified']=True;await send('play '+row['setupMoveUci']);b.push_uci(row['setupMoveUci']);start_i=0
  for i in range(start_i,len(row['solutionUci']),2):
   cp=key+'_ply'+str(i)+'.bin';ACTIVE[key].update(stage='searching',solver_moves_matched=attempt['moves_matched'],updated_at=utc())
   atom(meta_path,{'solver_ply':i,'fen':b.fen(),'checkpoint':cp,'attempt':attempt})
   await send('set-checkpoint '+str(WORK/cp));await send('go');reply=await until('bestmove ');actual=reply.split()[1];info=ACTIVE[key].get('completed','')
   if 'completed_board_hex='+bh(b) not in info:raise RuntimeError('ROM board mismatch at solver move '+str(i//2+1))
   if 'illegal_opcodes=0' not in info:raise RuntimeError('Illegal emulated opcode')
   m=chess.Move.from_uci(actual)
   if m not in b.legal_moves:raise RuntimeError('Illegal emulator move '+actual)
   expected=row['solutionUci'][i];match=actual==expected
   step={'solver_index':i//2+1,'actual':actual,'expected':expected,'san':b.san(m),'fen':b.fen(),'rom_board_verified':True,'matched':match,'search_info':info};attempt['moves'].append(step);log('verified_solver_move',**step)
   if not match:attempt.update(status='missed',score=0);break
   attempt['moves_matched']+=1;b.push(m)
   if i+1<len(row['solutionUci']):
    u=row['solutionUci'][i+1];log('scripted_opponent',uci=u,san=b.san(chess.Move.from_uci(u)));b.push_uci(u);await send('play '+u)
  else:
   assert attempt['moves_matched']==attempt['moves_required'];attempt.update(status='solved',score=1,all_solver_positions_verified=True,final_fen=b.fen(),checkmate=b.is_checkmate())
  attempt['finished_at']=utc();attempt['technical_retries_before_result']=TECHNICAL.get(key,{}).get('technical_attempts',0);RESULTS[key]=attempt;TECHNICAL.pop(key,None);atom(WORK/(key+'_result.json'),attempt)
  retry_file=WORK/(key+'_retry.json')
  if retry_file.exists():retry_file.unlink()
  for old in WORK.glob(key+'_ply*.bin'):old.unlink(missing_ok=True)
  meta_path.unlink(missing_ok=True)
 except asyncio.CancelledError:
  raise
 except Exception as exc:
  n=TECHNICAL.get(key,{}).get('technical_attempts',0)+1
  retry_base=float(os.environ.get('DELTA_RETRY_BASE_SECONDS','60'))
  attempt.update(status='technical',score=None,error=repr(exc),finished_at=utc(),technical_attempts=n,retry_at=time.time()+min(600,retry_base*2**min(4,n-1)));TECHNICAL[key]=attempt;atom(WORK/(key+'_retry.json'),attempt);heapq.heappush(RETRY,(attempt['retry_at'],ident))
  for old in WORK.glob(key+'_ply*.bin'):old.unlink(missing_ok=True)
  (WORK/(key+'_pending.json')).unlink(missing_ok=True)
 finally:
  if engine and engine.returncode is None:
   engine.terminate()
   try:await asyncio.wait_for(engine.wait(),10)
   except asyncio.TimeoutError:engine.kill();await engine.wait()
  PROCS.pop(key,None);ACTIVE.pop(key,None)
  if trace:trace.close()
async def lane(number):
 while not STOP:
  ident=None
  if RETRY and RETRY[0][0]<=time.time():_,ident=heapq.heappop(RETRY)
  elif NEW:ident=NEW.popleft()
  elif not RETRY:return
  else:await asyncio.sleep(min(1,max(.02,RETRY[0][0]-time.time())));continue
  key=str(ident)
  if key in RESULTS:continue
  if ident in INFLIGHT:raise RuntimeError('Duplicate concurrent puzzle assignment')
  INFLIGHT.add(ident);ATTEMPTED.add(ident)
  try:await run(BYID[ident],number)
  finally:INFLIGHT.remove(ident)
async def heartbeat():
 while not STOP:
  data=snapshot();atom(WORK/'status.json',data)
  try:await asyncio.to_thread(publish,A.shard,data)
  except Exception as e:print('FEED_ERROR',type(e).__name__,str(e),flush=True)
  await asyncio.sleep(30)
async def main():
 global STOP
 for row in sorted(ROWS,key=lambda r:r['index']):
  key=str(row['id']);old=saved_result(row);retry_file=WORK/(key+'_retry.json')
  if old:RESULTS[key]=old;ATTEMPTED.add(row['id'])
  elif retry_file.exists():
   r=json.loads(retry_file.read_text());TECHNICAL[key]=r;heapq.heappush(RETRY,(r['retry_at'],row['id']));ATTEMPTED.add(row['id'])
  else:NEW.append(row['id'])
 tasks=[asyncio.create_task(lane(n)) for n in range(A.workers)];feed=asyncio.create_task(heartbeat())
 done,pending=await asyncio.wait(tasks,timeout=A.budget)
 STOP=True
 for t in pending:t.cancel()
 await asyncio.gather(*tasks,return_exceptions=True);feed.cancel()
 try:await feed
 except asyncio.CancelledError:pass
 data=snapshot();atom(WORK/'status.json',data)
 try:await asyncio.to_thread(publish,A.shard,data)
 except Exception as e:print('FINAL_FEED_ERROR',repr(e),flush=True)
 print(json.dumps({'complete':len(RESULTS)==len(ROWS),'results':len(RESULTS),'paused':len(pending)}),flush=True)
asyncio.run(main())
