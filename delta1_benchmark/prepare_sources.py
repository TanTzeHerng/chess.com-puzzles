import csv,io,json,random,zipfile,urllib.request
from pathlib import Path
import chess,ijson
ROOT=Path(__file__).resolve().parent
ALPHA='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?{~}(^)[_]@#$'
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
 target=json.loads((ROOT/'target_manifest.json').read_text());ids={r['id'] for r in target['puzzles']}
 archive=Path('/tmp/delta1-source-puzzles-json.zip')
 if not archive.exists():
  req=urllib.request.Request('https://github.com/IchNukeDichWeg/chess.com-puzzles/releases/download/v2/puzzles-json.zip',headers={'User-Agent':'Delta1FullPuzzleGrader'})
  with urllib.request.urlopen(req,timeout=90) as src,archive.open('wb') as dst:
   while chunk:=src.read(1024*1024):dst.write(chunk)
 found={}
 with zipfile.ZipFile(archive) as z,z.open('puzzles.json') as f:
  for ident,row in ijson.kvitems(f,'',use_float=True):
   if int(ident) in ids:
    try:found[int(ident)]=normalize(row)
    except Exception as e:found[int(ident)]={'id':int(ident),'source_error':repr(e)}
    if len(found)==len(ids):break
 for r in target['puzzles']:
  row=found.get(r['id'],{'id':r['id'],'source_error':'ID absent from complete archive'})
  row.update({k:r[k] for k in ('index','lane','rating')});found[r['id']]=row
 (ROOT/'sources.json').write_text(json.dumps(list(found.values()),separators=(',',':')))
 print('Prepared complete sources:',len(found),'valid:',sum('source_error' not in r for r in found.values()),flush=True)
if __name__=='__main__':main()
