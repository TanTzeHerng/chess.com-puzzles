"""Verified legal predecessors to start real Delta-1 ROM search.
This deliberately does not change the original ROM, original Delta-1 run,
or puzzle solution. Exact target board, side, castling and EP are checked.
"""
import chess

def same_position(a,b):
 return (a.board_fen()==b.board_fen() and a.turn==b.turn
  and a.clean_castling_rights()==b.clean_castling_rights()
  and a.ep_square==b.ep_square)

def _check(pre,move,target):
 if not pre.is_valid() or move not in pre.legal_moves:return False
 result=pre.copy(stack=False)
 result.push(move)
 return same_position(result,target)

def trigger_for(target,preferred_before=None,preferred_uci=None):
 """Return (legal previous FEN, ordinary 4-character move, mode).
 The ROM receives the move through its keypad, never a fake 'think' flag.
 """
 if preferred_before is not None and preferred_uci and len(preferred_uci)==4:
  m=chess.Move.from_uci(preferred_uci)
  # En-passant capture needs a separately reconstructed prior EP flag.
  if not preferred_before.is_en_passant(m) and _check(preferred_before,m,target):
   return preferred_before.fen(en_passant='fen'),preferred_uci,'actual'
 mover=not target.turn
 if target.ep_square is not None:
  # A FEN EP square proves the immediately previous move was a pawn double
  # push. Reconstruct it as an exact board-legal ROM keypress.
  ep=target.ep_square
  direction=8 if mover==chess.WHITE else -8
  src=ep-direction
  dst=ep+direction
  if 0<=src<64 and 0<=dst<64 and target.piece_at(dst)==chess.Piece(chess.PAWN,mover) and target.piece_at(src) is None:
   pre=target.copy(stack=False)
   pre.remove_piece_at(dst)
   pre.set_piece_at(src,chess.Piece(chess.PAWN,mover))
   pre.turn=mover
   pre.ep_square=None
   pre.halfmove_clock=0
   if mover==chess.BLACK:pre.fullmove_number=max(1,target.fullmove_number-1)
   move=chess.Move(src,dst)
   if _check(pre,move,target):
    return pre.fen(en_passant='fen'),move.uci(),'synthetic_ep_double_push'
  raise ValueError('Cannot reconstruct valid EP-producing pawn move')
 # Choose a legal previous move that results in the EXACT target board.
 # The actual game history is not claimed to have been recovered.
 # Prefer low-impact knight/other ordinary quiet piece moves, leaving
 # kings and rooks (castling) untouched unless unavoidable.
 entries=sorted(target.piece_map().items(),
  key=lambda it: ({chess.KNIGHT:0,chess.BISHOP:1,chess.QUEEN:2,chess.ROOK:3,chess.PAWN:4,chess.KING:5}[it[1].piece_type],it[0]))
 empty=[sq for sq in chess.SQUARES if target.piece_at(sq) is None]
 for dst,piece in entries:
  if piece.color!=mover:continue
  if piece.piece_type==chess.PAWN and chess.square_rank(dst) in (0,7):continue
  for src in empty:
   pre=target.copy(stack=False)
   pre.remove_piece_at(dst)
   pre.set_piece_at(src,piece)
   pre.turn=mover
   pre.ep_square=None
   if piece.piece_type==chess.PAWN:pre.halfmove_clock=0
   else:pre.halfmove_clock=max(0,target.halfmove_clock-1)
   if mover==chess.BLACK:pre.fullmove_number=max(1,target.fullmove_number-1)
   move=chess.Move(src,dst)
   if _check(pre,move,target):
    return pre.fen(en_passant='fen'),move.uci(),'synthetic_verified_quiet'
 raise ValueError('No legal ordinary predecessor found for ROM search trigger')