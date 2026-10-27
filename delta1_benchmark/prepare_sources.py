import csv,io,json,random,zipfile,urllib.request,threading,datetime
from pathlib import Path
import chess,ijson
ROOT=Path(__file__).resolve().parent
ALPHA='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?{~}(^)[_]@#$'
DONE=threading.Event();SCANNED=0
def preparation_heartbeat():
 from github_feed import publish
 while not DONE.is_set():
  for shard in range(4):
   d={'schema':2,'epoch':'20261027T090152Z','run_id':'preparing','shard':shard,'heartbeat_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'level':'999999','initial_rating':2500,'initial_rd':350,'max_logical_workers':256,'actual_running_workers':0,'active':{},'eligible':0,'recent':[],'rating_bins':{},'counts':{'solved':0,'missed':0,'technical':0,'running':0,'queued':0},'state':'preparing','source_rows_scanned':SCANNED}
   try:publish(shard,d)
   except Exception as e:print('SOURCE_FEED_ERROR',repr(e),flush=True)
  DONE.wait(30)
def normalize(row):
 b=chess.Board(row['initialFen']);moves=[]
 for i in range(0,len(row['tcnMoveList']),2):
  a,t=map(ALPHA.index,row['tcnMoveList'][i:i+2]);promo=''
  if t>63:promo='qnrbk'[(t-64)//3];t=a+(-8 if a<16 else 8)+(t-64)%3-1
  u=chess.square_name(a)+chess.square_name(t)+promo;assert chess.Move.from_uci(u) in b.legal_moves
  b.push_uci(u);moves.append(u)
 if len(moves)<2 or len(moves)%2:raise ValueError('Complete line must end on solver move')
 return {'id':int(row['id']),'rating':int(row['rating']),'initialFen':row['initialFen'],'setupMoveUci':moves[0],'solutionUci':moves[1:],'colorOfUser':row['colorOfUser'],'tcnMoveList':row['tcnMoveList']}
def main():
 global SCANNED
 threading.Thread(target=preparation_heartbeat,daemon=True).start()
 original=[]
 archive=Path('/tmp/delta1-source-puzzles-json.zip')
 if not archive.exists():
  req=urllib.request.Request('https://github.com/IchNukeDichWeg/chess.com-puzzles/releases/download/v2/puzzles-json.zip',headers={'User-Agent':'Delta1FullPuzzleGrader'})
  with urllib.request.urlopen(req,timeout=90) as src,archive.open('wb') as dst:
   while chunk:=src.read(1024*1024):dst.write(chunk)
 found={}
 with zipfile.ZipFile(archive) as z,z.open('puzzles.json') as f:
  for ident,row in ijson.kvitems(f,'',use_float=True):
   SCANNED+=1
   try:rating=int(row['rating'])
   except (KeyError,ValueError,TypeError):continue
   if rating<2500:continue
   try:item=normalize(row)
   except Exception as e:item={'id':int(ident),'rating':rating,'initialFen':row.get('initialFen'),'tcnMoveList':row.get('tcnMoveList'),'source_error':repr(e)}
   found[int(ident)]=item
 first=[r['id'] for r in original if r['id'] in found];seen=set(first);remaining=[i for i in found if i not in seen]
 random.Random(20261027).shuffle(remaining);ordered=[]
 for index,ident in enumerate(first+remaining):
  row=found[ident];row.update(index=index,lane=index%256);ordered.append(row)
 (ROOT/'sources.json').write_text(json.dumps(ordered,separators=(',',':')))
 (ROOT/'source_metadata.json').write_text(json.dumps({'epoch':'20261027T090152Z','total_eligible':len(ordered),'min_rating':2500,'max_rating':None,'original_prefix_preserved':len(first),'seed':20261027,'source_errors':sum('source_error' in r for r in ordered)}))
 print('FULL_DATASET_ELIGIBLE',len(ordered),'source_errors',sum('source_error' in r for r in ordered),flush=True)
 DONE.set()
if __name__=='__main__':main()
