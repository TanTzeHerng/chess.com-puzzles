import collections,gzip,io,ijson,json,pathlib,sys,zipfile,chess,chess.pgn
source=json.loads(gzip.open('/tmp/torture-source/sources-full.json.gz','rt').read())
wanted={int(x['id']):x for x in source}
found={};stats=collections.Counter();fail_samples={}
with zipfile.ZipFile('/tmp/torture-source/puzzles-json.zip') as z:
 names=[n for n in z.namelist() if n.lower().endswith('puzzles.json')]
 assert len(names)==1,names
 with z.open(names[0]) as f:
  for n,(key,row) in enumerate(ijson.kvitems(f,'',use_float=True),1):
   ident=int(key)
   if ident not in wanted:continue
   out={'id':ident,'gameLiveId':row.get('gameLiveId'),'gameId':row.get('gameId')}
   pgn=row.get('pgn') or ''
   if not pgn:
    stats['missing_pgn']+=1;out.update(status='missing_pgn')
   else:
    try:
     game=chess.pgn.read_game(io.StringIO(pgn))
     if game is None:raise ValueError('Empty PGN')
     if game.errors:raise ValueError('PGN parse errors: '+str(game.errors[:2]))
     b=game.board()
     goal=chess.Board(wanted[ident]['initialFen'])
     def matching(a,target):
      return a.board_fen()==target.board_fen() and a.turn==target.turn and a.clean_castling_rights()==target.clean_castling_rights() and (a.ep_square==target.ep_square or not target.has_legal_en_passant())
     matched=matching(b,goal)
     uci=[];nply=0
     if not matched:
      for m in game.mainline_moves():
       if m not in b.legal_moves:break
       uci.append(b.uci(m));b.push(m);nply+=1
       if matching(b,goal):matched=True;break
     if matched:
      out.update(status='verified',game_start_fen=game.board().fen(),history_uci=uci,
       history_plies=nply,position_fen=b.fen(en_passant='fen'))
      stats['verified']+=1
     else:
      out.update(status='pgn_position_not_found',game_start_fen=game.board().fen(),
       found_plies=nply,expected_fen=goal.fen(en_passant='fen'))
      stats['position_not_found']+=1
    except Exception as exc:
     out.update(status='parse_error',error=repr(exc)[:320])
     stats['parse_error']+=1
   found[ident]=out
   if out['status']!='verified' and len(fail_samples)<15:fail_samples[str(ident)]=out
   if len(found)%2000==0:print('HISTORY_PROGRESS',len(found),'STATS',dict(stats),flush=True)
   if len(found)==len(wanted):break
assert len(found)==len(wanted),(len(found),len(wanted))
target='/tmp/torture-source/original-game-histories.json.gz'
with gzip.open(target,'wt',compresslevel=8) as out:
 json.dump({'dataset_count':len(wanted),'histories':found,'stats':dict(stats),'samples':fail_samples},out,separators=(',',':'))
print('HISTORY_EXTRACTION_DONE',len(found),'STATS',dict(stats),'OUTPUT',pathlib.Path(target).stat().st_size,flush=True)
