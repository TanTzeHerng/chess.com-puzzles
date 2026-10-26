# Safrad 2.1 vs Chess.com 2500+ puzzles

Windows GitHub Actions executes the original **Safrad 2.1.35.210** engine on the 19,492 puzzles rated 2500+ in the September 2026 Chess.com tactics snapshot. This is a cloud benchmark, not a run on the user's PC.

## Live checkpoints (no Actions logs needed)

| Cloud runner shard | Current state |
| --- | --- |
| 0 | [Live shard 0](progress/shard-00.json) |
| 1 | [Live shard 1](progress/shard-01.json) |
| 2 | [Live shard 2](progress/shard-02.json) |
| 3 | [Live shard 3](progress/shard-03.json) |

Each JSON is **committed directly by the running Windows job** every ~45 seconds, separate from GitHub Actions log delivery.

Read `status`, `heartbeat_utc`, `completed_count`, `worker_count`, `worker_calibration`, `remaining_count`, and `workers_active`. In `workers`, each active worker contains:

- `puzzle_id`, `puzzle_rating`, `solver_move_number`, `fen`, `expected_solution_move`
- `search_elapsed_seconds`, `remaining_seconds`, `last_update_utc`
- `analysis.depth`, `analysis.nodes`, `analysis.score`, `analysis.pv`
- `analysis.last_info` and `analysis.raw_tail`: **real unfinished UCI lines from Safrad**, not reconstructed analysis.

When Safrad doesn't report a field, it stays `null`. The complete recent search output is not fabricated. The benchmark uses `go infinite` and sends `stop` at exactly 600 seconds per solver move; premature `bestmove` is a technical error and is replayed instead of being scored.

A puzzle is solved only if **every** solver move matches the recorded solution. The opponent's replies are replayed from the source dataset. Technical failures are separate and are retried.

Progress is resumable: each cloud shard restores previously completed puzzle results from its GitHub checkpoint. Later checkpoints compress historical records inside `compressed_results_gzip_b64` to keep the live JSON readable.

## Worker calibration

Workers are scaled by actual repeated **simultaneously searching Safrad processes**. Calibration observes process survival, available RAM, and time to respond to UCI commands. **The number of logical CPU cores is not used** as the worker limit. Calibration is a finite stability test; it does not prove that an even larger worker count would never work. More concurrent engines share the runner's computing capacity, potentially reducing effective search depth per 600-second move.

## Run

[Safrad 2.1 Actions workflow](../../actions/workflows/safrad21-puzzles.yml)

Source engine: [Safrad 2.1 official release](https://sx.rosada.cz/projects/safrad-2.1)

Dataset: [Chess.com tactics snapshot documentation](https://github.com/IchNukeDichWeg/chess.com-puzzles)

The hosted Windows workflow resumes automatically on scheduled runs and can be launched manually through **Run workflow**.
