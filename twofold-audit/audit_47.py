#!/usr/bin/env python3
"""Audit exactly the 47 originally flagged Chess.com decision positions with automatic twofold Stockfish 17.1."""
import argparse, csv, json, sys, time, traceback
from pathlib import Path
import chess
from reanalyze_twofold import Engine, class_label, append_jsonl, utcnow

P=Path(__file__).resolve().parent
def load_csv(path):
    return list(csv.DictReader(open(path, encoding='utf-8-sig', newline='')))

def fen6(fen):
    x=fen.split()
    return ' '.join(x+['0','1']) if len(x)==4 else fen

def equivalent(a,b):
    # Compare full repetition identity: pieces, turn, castling and legal EP.
    return (a.board_fen()==b.board_fen() and a.turn==b.turn
            and a.clean_castling_rights()==b.clean_castling_rights()
            and a.has_legal_en_passant()==b.has_legal_en_passant()
            and (not a.has_legal_en_passant() or a.ep_square==b.ep_square))

def locate(record, old):
    hist=[record['setupMoveUci']]+record['solutionUci'].split()
    board=chess.Board(fen6(record['initialFen']))
    target=chess.Board(fen6(old['original_fen']))
    found=[]
    for i in range(len(hist)):
        if equivalent(board,target) and i>=1 and (i-1)%2==0:
            found.append((i, hist[:i], board.fen(), hist[i]))
        mv=chess.Move.from_uci(hist[i])
        if mv not in board.legal_moves:raise ValueError(f"source move not legal: {mv} at {i}")
        board.push(mv)
    if len(found)!=1:raise ValueError(f"exact flagged position match count {len(found)}, expected 1")
    return found[0]

def pv_twofold(origin, initial_fen, prefix, pv):
    # Check if the displayed PV contains a second occurrence, not a proof of absence beyond it.
    b=chess.Board(fen6(initial_fen)); seen={b._transposition_key():0}
    for n,m in enumerate(prefix,1):
        b.push_uci(m)
        k=b._transposition_key()
        if k in seen:return {'in_history':True,'first':seen[k],'second':n}
        seen[k]=n
    for n,m in enumerate(pv.split(),len(prefix)+1):
        try:
            move=chess.Move.from_uci(m)
            if move not in b.legal_moves:break
            b.push(move)
            k=b._transposition_key()
            if k in seen:return {'in_pv':True,'first':seen[k],'second':n,'move':m}
            seen[k]=n
        except Exception:break
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--engine',default='sf-17.1/src/stockfish')
    ap.add_argument('--group',type=int,default=0)
    ap.add_argument('--groups',type=int,default=4)
    ap.add_argument('--threads',type=int,default=2)
    ap.add_argument('--hashmb',type=int,default=192)
    ap.add_argument('--discover-ms',type=int,default=5000)
    ap.add_argument('--verify-ms',type=int,default=18000)
    ap.add_argument('--max-verify',type=int,default=4)
    ap.add_argument('--out',default='audit47_results.jsonl')
    ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args()
    originals=load_csv('twofold-audit/original_47_mate_recheck.csv')
    sources=load_csv('flagged_40_positions.csv')+load_csv('twofold-audit/recovered_seven.csv')
    by_id={int(x['id']):x for x in sources}
    assert len(originals)==47 and len(by_id)==47, (len(originals),len(by_id))
    entries=[]
    for j,old in enumerate(originals):
        pid=int(old['puzzle_id'])
        if pid not in by_id:raise ValueError(f"source missing {pid}")
        try:
            k,prefix,fen,recorded=locate(by_id[pid],old)
            board=chess.Board(fen6(fen))
            candidates=[old['first_move'],old['second_move']]
            for mv in candidates:
                if chess.Move.from_uci(mv) not in board.legal_moves:
                    raise ValueError(f"historical alternative {mv} is illegal")
            entries.append({'puzzle_id':pid,'rating':int(old['rating']),
                'history_uci':prefix,'initial_fen':by_id[pid]['initialFen'],
                'flagged_fen':fen,'original_fen':old['original_fen'],
                'historical_group':old['assessment'],
                'historical_first_move':candidates[0],
                'historical_second_move':candidates[1],
                'recorded_move':recorded,
                'candidate_moves':candidates,
                'decision_index':(k-1)//2+1,
                'source_url':by_id[pid]['source_puzzle_url']})
        except Exception as e:
            raise RuntimeError(f"Unable to reconstruct original flagged position {pid}: {e}") from e
    selected=[d for j,d in enumerate(entries) if j%args.groups==args.group]
    print('VALIDATED',len(entries),'exact source-history positions; group',args.group,'selected',len(selected),flush=True)
    if args.dry_run:
        for d in selected:print(d['puzzle_id'],d['decision_index'],d['candidate_moves'],d['flagged_fen'],flush=True)
        return
    already=set()
    out=Path(args.out)
    if out.exists():
        for line in out.read_text().splitlines():
            try:
                x=json.loads(line)
                if x['status']=='complete':already.add(x['puzzle_id'])
            except Exception:pass
    engine=Engine(args.engine,args.threads,args.hashmb)
    failures=0
    try:
        for j,d in enumerate(selected,1):
            pid=d['puzzle_id']
            if pid in already:continue
            print(f"[{j}/{len(selected)}] id={pid} decision={d['decision_index']} candidates={d['candidate_moves']}",flush=True)
            x={'timestamp_utc':utcnow(),**d,
               'status':'complete','rule':'automatic_twofold_repetition',
               'engine':'official Stockfish 17.1 patched for automatic twofold',
               'settings':{'threads':args.threads,'hashmb':args.hashmb,'discover_ms':args.discover_ms,'verify_ms':args.verify_ms}}
            try:
                scan=engine.search(d['initial_fen'],d['history_uci'],args.discover_ms,8)
                x['discovery']=scan
                moves=list(dict.fromkeys(d['candidate_moves']+
                    [v['move'] for v in scan['lines'] if class_label(v) in ('forced_mate_found','evaluated_win_not_proven')]))
                checked=[]
                for m in moves[:max(2,args.max_verify)]:
                    info=engine.search(d['initial_fen'],d['history_uci'],args.verify_ms,1,searchmove=m)
                    line=info['lines'][0] if info['lines'] else None
                    checked.append({'move':m,'label':class_label(line),
                        'analysis':line,'pv_repetition':pv_twofold(None,d['initial_fen'],d['history_uci'],line['pv']) if line else None})
                    print('   ',m,checked[-1]['label'],
                          line['score_type'] if line else None,line['score'] if line else None,flush=True)
                x['verified_moves']=checked
            except Exception as exc:
                x['status']='error';x['error']=repr(exc);failures+=1
                print('ERROR',pid,repr(exc),flush=True)
            append_jsonl(out,x)
    finally:engine.close()
    print('completed group',args.group,'failures',failures,flush=True)
    if failures:sys.exit(1)

if __name__=='__main__':main()
