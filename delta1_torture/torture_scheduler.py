"""Delta-1 Puzzle Torture: round-robin indefinite time-sliced chess problem solving.
Only this experiment's standalone ROM is used. Full F8 state persists per puzzle.
"""
import argparse,asyncio,collections,datetime,json,math,os,pathlib,time,zipfile,subprocess,urllib.request,base64,bisect
import chess

P=argparse.ArgumentParser()
P.add_argument('--shard',type=int,default=0)
P.add_argument('--workers',type=int,default=8)
P.add_argument('--budget',type=int,default=18000)
P.add_argument('--work',default='delta1_torture/work')
P.add_argument('--dry-run',action='store_true')
A=P.parse_args()
assert 0<=A.shard<4 and 1<=A.workers<=16
ROOT=pathlib.Path(__file__).resolve().parent
WORK=pathlib.Path(A.work).resolve()
WORK.mkdir(parents=True,exist_ok=True)
EXE=ROOT/'torture_engine'
if os.name=='nt':EXE=ROOT/'torture_engine.exe'
ROWS=json.loads((ROOT/'sources.json').read_text())
SHARD_ROWS=[x for x in ROWS if x['index']%4==A.shard]
SOURCE={str(x['id']):x for x in SHARD_ROWS}
STATES={}
for f in WORK.glob('puzzle-*.json'):
 try:
  v=json.loads(f.read_text())
  if str(v['id']) in SOURCE:STATES[str(v['id'])]=v
 except (OSError,ValueError,KeyError):pass
EPOCH='20261028-PUZZLE-TORTURE-V1'
LEDGER=WORK/'donaldrumpo-events.jsonl'
EVENTS={}
if LEDGER.exists():
 for line in LEDGER.read_text().splitlines():
  try:
   o=json.loads(line);EVENTS[o['event_id']]=o
  except ValueError:pass
LOCK=asyncio.Lock()
START=time.monotonic()
STOP=False
ACTIVE={}
RUN_ID=os.environ.get('GITHUB_RUN_ID','local-testing')
DONALD={'rating':2500.,'rd':350.,'events':0}
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
def atom(p,data):
 p=pathlib.Path(p);t=p.with_suffix(p.suffix+'.tmp')
 t.write_text(json.dumps(data,separators=(',',':')))
 t.replace(p)
def bh(b):
 return bytes(((v.piece_type if v.color else -v.piece_type)&255) if (v:=b.piece_at(i)) else 0 for i in range(64)).hex()
def glicko_event(r,rd,opponent,score):
 # Glicko-1, one trial per rating period; puzzle benchmark opponent RD=0.
 q=math.log(10)/400
 expected=1/(1+10**((opponent-r)/400))
 inv=1/(rd*rd)+q*q*expected*(1-expected)
 return r+(q*(score-expected))/inv,1/math.sqrt(inv)
def replay_rating():
 r,rd=2500.,350.
 for e in sorted(EVENTS.values(),key=lambda x:(x['utc'],x['event_id'])):
  r,rd=glicko_event(r,rd,e['puzzle_rating'],e['score'])
 DONALD.update(rating=r,rd=rd,events=len(EVENTS))
replay_rating()
def statefile(ident):return WORK/('puzzle-'+str(ident)+'.json')
def binfile(ident):return WORK/('puzzle-'+str(ident)+'.f8')
def source_check(row):
 if row.get('source_error'):raise ValueError('Source decode error: '+row['source_error'])
 b=chess.Board(row['initialFen'])
 if not b.is_valid():raise ValueError('Invalid source FEN')
 # Unsupported original historical rights must never be silently invented.
 if b.castling_rights or b.ep_square is not None:raise ValueError('Unverifiable FEN castle/EP rights')
 for color in (chess.WHITE,chess.BLACK):
  home=chess.E1 if color else chess.E8
  if b.king(color)==home and any(b.piece_at(q)==chess.Piece(chess.ROOK,color) for q in ((chess.A1,chess.H1) if color else (chess.A8,chess.H8))):
   raise ValueError('Ambiguous FEN rights: unmoved king and rook')
 for u in [row['setupMoveUci']]+row['solutionUci']:
  move=chess.Move.from_uci(u)
  if move not in b.legal_moves:raise ValueError('Illegal scripted source move '+u)
  if len(u)!=4:raise ValueError('Underpromotion/promotion adapter not verified for torture')
  b.push(move)
def board_from_history(row,st):
 b=chess.Board(row['initialFen'])
 for u in st['applied']:
  m=chess.Move.from_uci(u)
  if m not in b.legal_moves:raise ValueError('Invalid saved move history '+u)
  b.push(m)
 return b
def make_state(row):
 return {'id':row['id'],'rating':row['rating'],'status':'pending',
   'applied':[row['setupMoveUci']],'solver_index':0,
   'total_emulated_seconds':0,'move_emulated_seconds':0,
   'next_slice_seconds':30,'attempts':0,'matched_moves':0,
   'last_probe':None,'technical_errors':0,'error':None,
   'updated_at':utc(),'started_at':utc()}
def recent_results(limit=20):
 return sorted(({'id':x['id'],'rating':x['rating'],'status':x['status'],
   'elapsed':x['total_emulated_seconds'],'attempts':x['attempts'],
   'matched_moves':x['matched_moves'],'last_probe':x.get('last_probe'),
   'updated_at':x['updated_at']} for x in STATES.values()),
   key=lambda v:(v['updated_at'],v['id']),reverse=True)[:limit]
def snapshot():
 count=collections.Counter(x['status'] for x in STATES.values())
 total_s=sum(x['total_emulated_seconds'] for x in STATES.values())
 return {'schema':1,'experiment':'puzzle torture','rating_name':'Donaldtrumpo',
  'glicko_variant':'Glicko-1, wins-only completed puzzles, one trial per rating period, puzzle RD=0',
  'epoch':EPOCH,'run_id':RUN_ID,'shard':A.shard,'heartbeat_utc':utc(),
  'state':'running' if not STOP else 'between_runners',
  'rom_patch':'0x0d2c:5c=>2b','level':'999999','total_eligible':len(ROWS),
  'shard_puzzles':len(SHARD_ROWS),'rated':DONALD,
  'counts':{'solved':count['solved'],'blocked':count['blocked'],
   'technical':count['technical'],'in_rotation':count['pending']+count['searching'],
   'touched':len(STATES),'never_started':len(SHARD_ROWS)-len(STATES),
   'active_physical_workers':len(ACTIVE),'rating_events':len(EVENTS)},
  'active':ACTIVE.copy(),'total_emulated_seconds':total_s,'recent':recent_results(),
  'solve_events':sorted(EVENTS.values(),key=lambda e:(e['utc'],e['event_id']))}
def parse_info(line):
 ans={}
 for frag in line.split()[1:]:
  if '=' in frag:
   k,v=frag.split('=',1);ans[k]=v
 return ans
async def write_event(row,st,score,actual):
 event_id=str(row['id'])+':'+str(st['solver_index'])+':'+str(st['attempts'])
 async with LOCK:
  if event_id not in EVENTS:
   event={'event_id':event_id,'id':row['id'],'solver_index':st['solver_index'],
    'puzzle_rating':row['rating'],'score':score,'actual':actual,
    'utc':utc(),'elapsed':st['total_emulated_seconds']}
   ordered_times=sorted(float(x['elapsed']) for x in EVENTS.values())
   event['time_distribution_rank']=bisect.bisect_right(ordered_times,float(event['elapsed']))
   event['time_distribution_count']=len(ordered_times)+1
   next_rating,next_rd=glicko_event(DONALD['rating'],DONALD['rd'],event['puzzle_rating'],1)
   event['donaldtrumpo_rating_after']=next_rating
   event['donaldtrumpo_rd_after']=next_rd
   with LEDGER.open('a',encoding='utf8') as f:f.write(json.dumps(event,separators=(',',':'))+'\n')
   EVENTS[event_id]=event
   replay_rating()
   # Exact sorted distribution at this solve; event ledger is its lossless history.
   atom(WORK/'sorted_distribution_latest.json',{'utc':event['utc'],'rating_name':'Donaldtrumpo',
    'donaldtrumpo':DONALD.copy(),'emulated_seconds_ascending':sorted(ordered_times+[float(event['elapsed'])])})
async def command(eng,message,prefix,timeout=180):
 if eng.returncode is not None:raise RuntimeError('Engine exited before command')
 eng.stdin.write((message+'\n').encode())
 await eng.stdin.drain()
 while True:
  line=await asyncio.wait_for(eng.stdout.readline(),timeout=timeout)
  if not line:raise RuntimeError('ROM emulator died during '+message)
  txt=line.decode('utf8','replace').strip()
  if txt.startswith('error ') or txt.startswith('fatal '):raise RuntimeError(txt)
  if txt.startswith(prefix):return txt
def new_engine():
 return asyncio.create_subprocess_exec(str(EXE),stdin=asyncio.subprocess.PIPE,
   stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
async def attempt(row,st,eng,worker):
 ident=row['id'];key=str(ident)
 try:
  if binfile(ident).exists():
   line=await command(eng,'load '+str(binfile(ident)),'loaded board_hex=',30)
   # Checkpoint restores all F8 CPU, ROM, timer and search registers. Never
   # restart a hard puzzle's current solver move from the beginning.
  else:
   b=board_from_history(row,st)
   if b.castling_rights or b.ep_square is not None:
    raise RuntimeError('Unsafe rights in resumed solver position')
   ready=await command(eng,'setup '+b.fen(),'ready ',45)
   setup_info=parse_info(ready)
   if setup_info.get('board_hex')!=bh(b):
    raise RuntimeError('ROM keypad setup failed independent 64-square verification')
   expected_color='white' if b.turn==chess.WHITE else 'black'
   if setup_info.get('computer_color')!=expected_color:
    raise RuntimeError('ROM side-to-move setup mismatch')
  b=board_from_history(row,st)
  assert st['solver_index']<len(row['solutionUci'][::2])
  expected=row['solutionUci'][2*st['solver_index']]
  await command(eng,'watch '+expected,'watching ',20)
  seconds=min(3600,max(30,int(st['next_slice_seconds'])))
  ACTIVE[worker]={'id':ident,'puzzle_rating':row['rating'],'slice_seconds':seconds,
    'cumulative_seconds':st['total_emulated_seconds'],'updated_at':utc(),
    'stage':'searching','solver_index':st['solver_index']}
  raw=await command(eng,'advance '+str(seconds),'advanced ',180)
  info=parse_info(raw)
  if info.get('illegal_opcodes')!='0':raise RuntimeError('Illegal F8 emulated opcode')
  spent=float(info['seconds'])
  if not 0<spent<=seconds+0.01:raise RuntimeError('Incorrect emulator time accounting')
  st['total_emulated_seconds']+=spent
  st['move_emulated_seconds']+=spent
  hit=info.get('flash_seen')=='1'
  st['attempts']+=1
  st['last_probe']=expected if hit else None
  st['updated_at']=utc()
  if hit:
   # The correct solver move has actually flashed on Delta-1's four-digit
   # display. No requirement for the ROM to settle on that move.
   st['applied'].append(expected)
   st['matched_moves']+=1
   st['solver_index']+=1
   st['move_emulated_seconds']=0
   st['next_slice_seconds']=30
   if st['solver_index']==len(row['solutionUci'][::2]):
    st['status']='solved';st['completed_at']=utc()
    await write_event(row,st,1,expected)
   else:
    st['applied'].append(row['solutionUci'][2*(st['solver_index']-1)+1])
    st['status']='searching'
   # A new solver move begins from its canonical reference position.
   # Never mistake a ROM's temporary search board for the actual board.
   binfile(ident).unlink(missing_ok=True)
  else:
   st['next_slice_seconds']=min(3600,int(max(30,st['next_slice_seconds']*2)))
   st['status']='searching'
   # All F8 CPU/RAM/timer/search registers are serialized on each pause.
   await command(eng,'save '+str(binfile(ident)),'saved ',45)
  atom(statefile(ident),st);STATES[key]=st
  ACTIVE.pop(worker,None)
  return st['status']
 except Exception:
  ACTIVE.pop(worker,None)
  raise
async def worker_task(index,queue,deadline):
 label='S'+str(A.shard)+'W'+str(index)
 eng=await new_engine()
 try:
  while time.monotonic()<deadline:
   try:ident=queue.get_nowait()
   except asyncio.QueueEmpty:break
   row=SOURCE[str(ident)]
   st=STATES.get(str(ident))
   if st is None:
    try:source_check(row);st=make_state(row)
    except Exception as e:
     st={'id':ident,'rating':row['rating'],'status':'blocked','error':str(e),
       'updated_at':utc(),'total_emulated_seconds':0,'attempts':0,'matched_moves':0}
     STATES[str(ident)]=st;atom(statefile(ident),st)
   if st['status'] in ('solved','blocked','technical'):
    queue.task_done();continue
   try:
    await attempt(row,st,eng,label)
   except (Exception,asyncio.TimeoutError) as e:
    st['technical_errors']=st.get('technical_errors',0)+1
    st['status']='technical' if st['technical_errors']>=4 else 'searching'
    st['error']=repr(e);st['updated_at']=utc()
    atom(statefile(ident),st);STATES[str(ident)]=st
    try:eng.kill();await eng.wait()
    except ProcessLookupError:pass
    eng=await new_engine()
   if st['status']=='searching':
    queue.put_nowait(ident)
   queue.task_done()
 finally:
  if eng.returncode is None:
   eng.terminate()
   try:await asyncio.wait_for(eng.wait(),10)
   except asyncio.TimeoutError:eng.kill();await eng.wait()
async def monitor(deadline):
 from feed import publish
 last_checkpoint=time.monotonic()
 while time.monotonic()<deadline:
  d=snapshot()
  atom(WORK/'status.json',d)
  try:await asyncio.to_thread(publish,A.shard,d)
  except Exception as e:print('FEED_WARNING',repr(e),flush=True)
  if time.monotonic()-last_checkpoint>=600:
   try:
    result=await asyncio.to_thread(subprocess.run,
     [os.environ.get('PYTHON','python3'),str(ROOT/'checkpoint.py'),'save',str(A.shard),str(WORK)],
     capture_output=True,text=True,timeout=150)
    print('TORTURE_CHECKPOINT_HEARTBEAT',result.returncode,result.stdout[-350:],result.stderr[-350:],flush=True)
    if result.returncode==0:last_checkpoint=time.monotonic()
   except Exception as e:print('CHECKPOINT_WARNING',repr(e),flush=True)
  await asyncio.sleep(30)
async def main():
 global STOP
 deadline=time.monotonic()+A.budget
 q=asyncio.Queue()
 entries=[]
 for row in SHARD_ROWS:
  st=STATES.get(str(row['id']))
  if st and st['status'] in ('solved','blocked','technical'):continue
  entries.append((st['updated_at'] if st else '',row['index'],row['id']))
 for _,__,ident in sorted(entries):q.put_nowait(ident)
 print('PUZZLE_TORTURE_START',A.shard,len(entries),'workers',A.workers,'saved_state',len(STATES),flush=True)
 if A.dry_run:
  print(json.dumps(snapshot()));return
 watchers=asyncio.create_task(monitor(deadline))
 workers=[asyncio.create_task(worker_task(i,q,deadline)) for i in range(A.workers)]
 await asyncio.gather(*workers,return_exceptions=False)
 STOP=True
 watchers.cancel()
 try:await watchers
 except asyncio.CancelledError:pass
 atom(WORK/'status.json',snapshot())
 print('PUZZLE_TORTURE_CHECKPOINT',json.dumps(snapshot()['counts']),flush=True)
if __name__=='__main__':asyncio.run(main())
