# Delta-1 Puzzle Torture, Donaldtrumpo

Independent time-limit-stripped one-byte-ROM experiment on all 19,492 Chess.com puzzles rated 2500+. Does not change the earlier original-ROM grading run.

- Correct **solver move**: the exact expected UCI coordinates appear even briefly on the real four-digit emulated LED. `refresh_display()` observes the digits as the ROM writes them, without waiting for a finalized best move.
- A puzzle is **solved** only after **every solver move** in its solution has flashed during its respective search.
- The only rating events are **new solved puzzles**, one win per complete puzzle; no failed-search penalties. **Donaldtrumpo** uses Glicko-1 update mathematics, therefore does not decrease from successful events. Initial rating 2500, RD 350.
- Record the rating and the sorted **ascending cumulative emulated search times** of all solved puzzles on every new solve. A lossless append-only event ledger, insertion rank and latest sorted snapshot permit reconstructing every historical distribution. The 3D visualization plots rank, elapsed time and Donaldtrumpo rating.
- Search slices grow 30, 60, 120, 240 ... to 3600 emulated seconds per visit. A hard puzzle is **paused**, its complete F8 CPU/RAM/timers/search state is saved, and another puzzle gets the physical worker. Never restart the search of an unsolved move from zero.
- Four independent cloud shards, up to sixteen physical emulator processes each. Separate GitHub branch, release checkpoints, progress JSON, workflow and PC dashboard.
- Original FENs with unverified castling/en-passant rights or promotion sequences are **blocked as technical limitations**, not scored as chess failures. After a solver move flashes correctly, its next scripted position is reconstructed from the source FEN and full reference move history; ROM internal history prior to that move is not independently reconstructed. Be cautious with history-dependent puzzles.
- The ROM time limit is bypassed through the **single-byte 0x0D2C 0x5C=>0x2B** change. Original ROM checksum is checked at build time.
- Automation is subject to GitHub Actions free compute allowance and service availability, and does not guarantee perpetual execution.
