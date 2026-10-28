"""Delta-1 Puzzle Torture: round-robin indefinite time-sliced chess problem solving.
Only this experiment's standalone ROM is used. Full F8 state persists per puzzle.
"""
import argparse,asyncio,collections,datetime,json,math,os,pathlib,time,zipfile,subprocess,urllib.request,base64,bisect
import chess
from position_trigger import trigger_for

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
def ambiguous_historical_castling(row):
 # The original FEN has no castling rights, but a king and one of its
 # home rooks are still on their starting squares. Delta-1 may castle
 # illegally; that is an ordinary failed candidate, not a technical error.
 if row.get('source_error'):return False
 b=chess.Board(row['initialFen'])
 if b.castling_rights or b.ep_square is not None:return False
 return any(
   b.king(color)==(chess.E1 if color else chess.E8)
   and any(b.piece_at(sq)==chess.Piece(chess.ROOK,color)
    for sq in ((chess.A1,chess.H1) if color else (chess.A8,chess.H8)))
   for color in (chess.WHITE,chess.BLACK))
CASTLING_220_IDS=frozenset(int(row['id']) for row in ROWS if ambiguous_historical_castling(row))
if len(CASTLING_220_IDS)!=220:raise RuntimeError('Castling ambiguity cohort changed: '+str(len(CASTLING_220_IDS)))
SHARD_CASTLING_IDS=sorted(int(row['id']) for row in SHARD_ROWS if int(row['id']) in CASTLING_220_IDS)
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
DONALD={'rating':None,'rd':None,'events':0}
BASELINE_SECONDS=99.0
BASELINE_TOTAL=len(ROWS)

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
def qualifies(st):
 # An early complete solve needs no more search; otherwise the actual,
 # cumulatively executed search duration must reach >=99 seconds.
 if st.get('status')=='solved':return True
 return bool(st.get('attempted_at')) and float(st.get('total_emulated_seconds',0))>=BASELINE_SECONDS and st.get('status') not in ('technical','blocked')
def rating_rows():
 out=[]
 for row in SHARD_ROWS:
  st=STATES.get(str(row['id']))
  if st is None or not qualifies(st):continue
  out.append((int(row['id']),int(row['rating']),st.get('attempted_at') or st.get('started_at') or EPOCH[:8],
    int(st['status']=='solved'),int(row['id'] in CASTLING_220_IDS)))
 return sorted(out,key=lambda v:(v[2],v[0]))
def baseline_progress():
 eligible=sum(1 for row in SHARD_ROWS
  if str(row['id']) in STATES and qualifies(STATES[str(row['id'])]))
 solved=sum(1 for st in STATES.values() if st.get('status')=='solved')
 blocked=sum(1 for st in STATES.values() if st.get('status')=='blocked')
 technical=sum(1 for st in STATES.values() if st.get('status')=='technical')
 return {'qualified':eligible,'total':len(SHARD_ROWS),
  'pending':len(SHARD_ROWS)-eligible,'solved':solved,'blocked':blocked,
  'technical':technical,'required_emulated_seconds_per_puzzle':BASELINE_SECONDS}
def glicko_batch(rows):
 # One Glicko-1 rating period with a fixed, identical set of puzzles.
 # Its denominator and RD stay fixed as provisional failures flip to wins.
 # This makes the resulting rating mathematically nondecreasing after the
 # 99-second qualification is complete for ALL 19,492 puzzles.
 r0,rd0=2500.,350.
 q=math.log(10)/400.
 inv=1/(rd0*rd0)
 margin=0.
 for ident,opponent,at,score,cohort in rows:
  expected=1/(1+10**max(-8,min(8,(opponent-r0)/400)))
  inv+=q*q*expected*(1-expected)
  margin+=q*(score-expected)
 return r0+margin/inv,1/math.sqrt(inv)
def replay_rating():
 rows=rating_rows()
 # Local shard numbers are only a progress diagnostic. They are NEVER
 # presented as the global Donaldtrumpo rating before all 19,492 qualify.
 rating,rd=(glicko_batch(rows) if rows else (None,None))
 DONALD.update(rating=rating,rd=rd,events=len(rows),
  wins=sum(x[3] for x in rows),
  provisional_failures=sum(1-x[3] for x in rows),
  baseline=baseline_progress())
replay_rating()
def statefile(ident):return WORK/('puzzle-'+str(ident)+'.json')
def binfile(ident):return WORK/('puzzle-'+str(ident)+'.f8')
def source_check(row):
 if row.get('source_error'):raise ValueError('Source decode error: '+row['source_error'])
 b=chess.Board(row['initialFen'])
 if not b.is_valid():raise ValueError('Invalid source FEN')
 # Unsupported original historical rights must never be silently invented.
 for color in (chess.WHITE,chess.BLACK):
  home=chess.E1 if color else chess.E8
  # These 220 positions are now explicitly eligible even if their
  # king and rook occupy the home squares without castling rights.
  # An illegal ROM castling candidate does not become a technical error.
  pass
 for u in [row['setupMoveUci']]+row['solutionUci']:
  move=chess.Move.from_uci(u)
  if move not in b.legal_moves:raise ValueError('Illegal scripted source move '+u)
  b.push(move)
def board_from_history(row,st):
 b=chess.Board(row['initialFen'])
 for u in st['applied']:
  m=chess.Move.from_uci(u)
  if m not in b.legal_moves:raise ValueError('Invalid saved move history '+u)
  b.push(m)
 return b
def recover_exhausted_technical():
 recovered=0;pending_input=0
 for key,st in STATES.items():
  if st.get('status')!='technical':continue
  err=st.get('error','')
  if 'Incorrect emulator time accounting' in err and binfile(st['id']).exists():
   st['status']='searching'
   st['technical_errors']=0
   st['error']='Recovered time-accounting tolerance; retained exact F8 checkpoint'
   st['updated_at']=utc()
   atom(statefile(st['id']),st);recovered+=1
  elif 'ROM side-to-move setup mismatch' in err:
   # Bad harness validation fired before any search; preserve all existing
   # puzzle history, but restore eligibility without penalizing the ROM.
   st['status']='searching'
   st['technical_errors']=0
   st['previous_harness_error']=err
   st['error']=None
   st['updated_at']=utc()
   atom(statefile(st['id']),st);recovered+=1
  elif 'Unsafe rights in resumed solver position' in err:
   st['status']='blocked'
   st['error']='Awaiting original-game history to reconstruct FEN rights'
   st['updated_at']=utc()
   atom(statefile(st['id']),st);pending_input+=1
  # All previous blanket input exclusions are obsolete. Reopen without
  # resetting genuine solver progress, including already found tactics.
  newly=0;still_unverified=0
  for key,st in STATES.items():
   error=str(st.get('error') or '')
   if st.get('status')=='blocked' and any(term in error for term in (
     'Unverifiable FEN castle/EP rights',
     'Underpromotion/promotion adapter not verified for torture',
     'Awaiting original-game history',
     'Unverifiable rights in continuation',
     'Ambiguous FEN rights')):
    row=SOURCE[key]
    if not st.get('applied'):
     st=make_state(row)
    else:
     st['status']='searching'
     st['technical_errors']=0
     st['previous_block_reason']=error
     st['error']=None
     st['updated_at']=utc()
    STATES[key]=st
    atom(statefile(st['id']),st)
    newly+=1
   elif st.get('status')=='technical' and any(term in error for term in (
       'watch requires 4-char move','Four-character moves only',
       'Unverifiable rights in continuation','Invalid slice seconds')):
    st['status']='searching'
    st['previous_harness_error']=error
    st['technical_errors']=0
    st['error']=None
    st['updated_at']=utc()
    atom(statefile(st['id']),st)
    newly+=1
  print('RECOVERED_SAVED_SEARCHES',recovered,'INPUT_BLOCKS_REOPENED',newly,flush=True)
def reopen_castling_220():
 reopened=0
 for ident in SHARD_CASTLING_IDS:
  key=str(ident)
  old=STATES.get(key)
  if old and old.get('status')=='blocked' and old.get('error')=='Ambiguous FEN rights: unmoved king and rook':
   st=make_state(SOURCE[key])
   st['previous_block_reason']=old['error']
   st['reopened_at']=utc()
   st['historically_ambiguous_castling_220']=True
   STATES[key]=st
   binfile(ident).unlink(missing_ok=True)
   atom(statefile(ident),st)
   reopened+=1
 # A durable cohort manifest allows retrospective Donaldtrumpo
 # recalculation with or without all of these puzzles.
 atom(WORK/'castling_220_manifest.json',{
  'cohort':'220 home-square historical-castling ambiguity puzzles',
  'all_220_ids':sorted(CASTLING_220_IDS),
  'shard_ids':SHARD_CASTLING_IDS,
  'illegal_castle_candidate_policy':'ordinary unsolved candidate; no technical error; no rating loss',
  'rating_inclusion':'After 99s qualifying phase all 220 cohort puzzles included; provisional unsolved 0, solved 1',
  'updated_at':utc()})
 print('CASTLING_220_REOPENED',reopened,'SHARD_COHORT',len(SHARD_CASTLING_IDS),flush=True)
def make_state(row):
 return {'id':row['id'],'rating':row['rating'],'status':'pending',
   'applied':[row['setupMoveUci']],'solver_index':0,
   'total_emulated_seconds':0,'move_emulated_seconds':0,
   'next_slice_seconds':30,'attempts':0,'matched_moves':0,
   'last_probe':None,'technical_errors':0,'error':None,
   'historically_ambiguous_castling_220':row['id'] in CASTLING_220_IDS,
   'updated_at':utc(),'started_at':utc(),'attempted_at':None}
def recent_results(limit=20):
 return sorted(({'id':x['id'],'rating':x['rating'],'status':x['status'],
   'elapsed':x['total_emulated_seconds'],'attempts':x['attempts'],
   'matched_moves':x['matched_moves'],'last_probe':x.get('last_probe'),
   'updated_at':x['updated_at']} for x in STATES.values()),
   key=lambda v:(v['updated_at'],v['id']),reverse=True)[:limit]
def snapshot():
 replay_rating()
 outcomes=rating_rows()
 count=collections.Counter(x['status'] for x in STATES.values())
 total_s=sum(x.get('total_emulated_seconds',0) for x in STATES.values())
 return {'schema':1,'experiment':'puzzle torture','rating_name':'Donaldtrumpo',
  'glicko_variant':'Glicko-1 single rating period for all 19492 puzzles after each has searched >=99 emulated seconds (or solved earlier); provisional failures become wins, fixed field, monotone rating',
  'epoch':EPOCH,'run_id':RUN_ID,'shard':A.shard,'heartbeat_utc':utc(),
  'state':'running' if not STOP else 'between_runners',
  'rom_patch':'0x0d2c:5c=>2b','level':'999999','total_eligible':len(ROWS),
  'shard_puzzles':len(SHARD_ROWS),'rated':DONALD,
  'rating_outcomes':outcomes,
  'baseline_99':baseline_progress(),
  'qualification_seconds':BASELINE_SECONDS,
  'rating_protocol_version':'torture-99-second-full-cohort-batch-Glicko1',
  'rated_attempted':len(outcomes),
  'provisional_failures':sum(1-r[3] for r in outcomes),
  'castling_220_ids':SHARD_CASTLING_IDS,
  'castling_220_status':{str(k):STATES[str(k)]['status'] for k in SHARD_CASTLING_IDS if str(k) in STATES},
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
    'historically_ambiguous_castling_220':int(row['id']) in CASTLING_220_IDS,
    'rating_protocol':'torture v2: one provisional failure per attempted unsolved puzzle; solve replaces failure',
    'utc':utc(),'elapsed':st['total_emulated_seconds']}
   ordered_times=sorted(float(x['elapsed']) for x in EVENTS.values())
   event['time_distribution_rank']=bisect.bisect_right(ordered_times,float(event['elapsed']))
   event['time_distribution_count']=len(ordered_times)+1
   # Recording a win changes one provisional failure into a success.
   # Rating is recomputed over every currently attempted puzzle; shard-only
   # ratings are advisory. The PC dashboard merges all four shards.
   with LEDGER.open('a',encoding='utf8') as f:f.write(json.dumps(event,separators=(',',':'))+'\n')
   EVENTS[event_id]=event
   replay_rating()
   event['shard_donaldtrumpo_rating_after']=DONALD['rating']
   event['shard_donaldtrumpo_rd_after']=DONALD['rd']
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
 expected=row['solutionUci'][2*st['solver_index']]
 try:
  if binfile(ident).exists():
   line=await command(eng,'load '+str(binfile(ident)),'loaded board_hex=',30)
   await command(eng,'watch '+expected,'watching ',20)
   # Checkpoint restores all F8 CPU, ROM, timer and search registers. Never
   # restart a hard puzzle's current solver move from the beginning.
  else:
   # FP/EP only places pieces; it does NOT start chess search.
   # Reconstruct the position BEFORE the most recent scripted move, and
   # enter that move via real keypad to launch Delta-1 search.
   b=board_from_history(row,st)
   reference_before=chess.Board(row['initialFen'])
   for u in st['applied'][:-1]:
    reference_before.push_uci(u)
   last=st['applied'][-1]
   trigger_fen,trigger_move,trigger_mode=trigger_for(b,reference_before,last)
   before=chess.Board(trigger_fen)
   ready=await command(eng,'setup '+trigger_fen,'ready ',45)
   setup_info=parse_info(ready)
   if setup_info.get('board_hex')!=bh(before):
    raise RuntimeError('ROM keypad setup failed independent 64-square verification')
   expected_color='black' if before.turn==chess.WHITE else 'white'
   if setup_info.get('computer_color')!=expected_color:
    raise RuntimeError('ROM side-to-move setup mismatch')
   # Arm before ENTER. Short tactical moves can flash while the keypad
   # itself is returning; arming afterwards silently misses them.
   await command(eng,'watch '+expected,'watching ',20)
   played=await command(eng,'play '+trigger_move,'played ',45)
   played_info=parse_info(played)
   if played_info.get('input_accepted')!='1':
    raise RuntimeError('Original ROM rejected legal search trigger: '+trigger_mode)
   # The ROM may already have made a move by the time ENTER returns.
   # Therefore the *post-ENTER* board is not required to match the exact
   # reference. The exact predecessor and chess-legal trigger WERE checked
   # before entering the ROM.
   st['search_trigger_mode']=trigger_mode
  if not st.get('attempted_at'):
    st['attempted_at']=utc()
    atom(statefile(ident),st)
  if not st.get('attempted_at'):
   # Old exact F8 checkpoints already contain active chess search.
   st['attempted_at']=st.get('started_at') or utc()
   atom(statefile(ident),st)
  b=board_from_history(row,st)
  assert st['solver_index']<len(row['solutionUci'][::2])

  # Give every puzzle its qualifying exposure before spending more time on
  # puzzles that already exceeded 99 seconds. Use an exact 99s first slice;
  # for checkpointed work, search only the actual remaining qualification.
  remaining=max(0.,BASELINE_SECONDS-float(st.get('total_emulated_seconds',0)))
  if remaining>0:
   seconds=max(0.1,round(remaining,4))
  else:
   seconds=min(3600,max(30,int(st['next_slice_seconds'])))
  ACTIVE[worker]={'id':ident,'puzzle_rating':row['rating'],'slice_seconds':seconds,
    'cumulative_seconds':st['total_emulated_seconds'],'updated_at':utc(),
    'stage':'searching','solver_index':st['solver_index']}
  raw=await command(eng,'advance '+str(seconds),'advanced ',180)
  info=parse_info(raw)
  if info.get('illegal_opcodes')!='0':raise RuntimeError('Illegal F8 emulated opcode')
  spent=float(info['seconds'])
  if not 0<spent<=seconds*1.02+1:raise RuntimeError('Incorrect emulator time accounting: '+str((seconds,spent)))
  st['total_emulated_seconds']+=spent
  st['move_emulated_seconds']+=spent
  if st['total_emulated_seconds']>=BASELINE_SECONDS:
   st['qualified_at']=st.get('qualified_at') or utc()
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
    try:
     source_check(row);st=make_state(row)
     STATES[str(ident)]=st
     atom(statefile(ident),st)
    except Exception as e:
     st={'id':ident,'rating':row['rating'],'status':'blocked','error':str(e),
       'updated_at':utc(),'total_emulated_seconds':0,'attempts':0,'matched_moves':0}
     STATES[str(ident)]=st;atom(statefile(ident),st)
   if st['status'] in ('solved','blocked','technical'):
    queue.task_done();continue
   try:
    await attempt(row,st,eng,label)
   except (Exception,asyncio.TimeoutError) as e:
    if isinstance(e,ValueError) and 'rights in continuation' in str(e):
     st['status']='blocked'
    else:
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
 recover_exhausted_technical()
 reopen_castling_220()
 # All V1 states were created from FP/EP board placement without playing
 # the setup move. The ROM did not enter chess search. Preserve the old release
 # checkpoints as evidence, but discard their non-searching F8 states and
 # reset the invalid accumulated chess-search durations.
 repaired=0
 for k,st in STATES.items():
  if st.get('status')!='searching' or st.get('search_initialized'):continue
  if st.get('matched_moves',0):continue
  st['legacy_idle_seconds']=st.get('total_emulated_seconds',0)
  st['attempted_at']=None
  st['total_emulated_seconds']=0
  st['move_emulated_seconds']=0
  st['attempts']=0
  st['technical_errors']=0
  st['next_slice_seconds']=30
  st['error']=None
  st['search_initialized']=True
  st['updated_at']=utc()
  binfile(st['id']).unlink(missing_ok=True)
  atom(statefile(st['id']),st)
  repaired+=1
 print('INVALID_IDLE_STATES_REINITIALIZED',repaired,flush=True)
 q=asyncio.Queue()
 entries=[]
 for row in SHARD_ROWS:
  st=STATES.get(str(row['id']))
  if st and st['status'] in ('solved','blocked','technical'):continue
  entries.append((st['updated_at'] if st else '',row['index'],row['id']))
 # Prioritize never-qualified puzzles; long-running search states retain
  # every CPU/RAM/timer bit and resume later.
 entries.sort(key=lambda z:(int(bool(STATES.get(str(z[2])) and qualifies(STATES[str(z[2])]))),z[0],z[1]))
 for _,__,ident in entries:q.put_nowait(ident)
 print('PUZZLE_TORTURE_START',A.shard,len(entries),'workers',A.workers,'saved_state',len(STATES),
   'BASELINE_99',baseline_progress(),flush=True)
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