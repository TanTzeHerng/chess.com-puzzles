"""Remote Maia3-79M one-node puzzle worker with resumable public progress."""
import gzip
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import chess
import chess.engine

SHARD = int(os.environ["MAIA_SHARD"])
SHARDS = int(os.environ.get("MAIA_SHARDS", "64"))
BRANCH = f"maia3-79m-puzzle2000-progress-{SHARD:02d}"
OUT = Path("maia3_live")
OUT.mkdir(exist_ok=True)
STATUS = OUT / "status.json"
JOURNAL = OUT / "results.jsonl.gz"
RECORDS = []


def command(*parts, check=True):
    return subprocess.run(parts, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def setup_branch():
    command("git", "config", "user.name", "maia3-benchmark-bot")
    command("git", "config", "user.email", "maia3-benchmark-bot@users.noreply.github.com")
    remote = command("git", "ls-remote", "--exit-code", "--heads", "origin", BRANCH, check=False)
    if remote.returncode == 0:
        command("git", "fetch", "--depth=1", "origin", BRANCH)
        command("git", "checkout", "-B", BRANCH, "FETCH_HEAD")
    else:
        command("git", "checkout", "-b", BRANCH)
    if JOURNAL.exists():
        with gzip.open(JOURNAL, "rt", encoding="utf-8") as f:
            RECORDS.extend(json.loads(line) for line in f if line.strip())
    print("CHECKPOINT_BRANCH", BRANCH, "resumed", len(RECORDS), flush=True)


def start_engine():
    argv = [sys.executable, "-m", "maia3.uci", "--model", "maia3-79m",
            "--elo", "2600", "--temperature", "0", "--top-p", "1",
            "--device", "cpu", "--no-use-amp", "--multipv", "1"]
    e = chess.engine.SimpleEngine.popen_uci(argv, timeout=1200)
    e.configure({"Elo": 2600, "SelfElo": 2600, "OppoElo": 2600,
                 "Temperature": "0", "TopP": "1"})
    return e


def assess(engine, puzzle):
    board = chess.Board(puzzle["initialFen"])
    board.push_uci(puzzle["setupMoveUci"])
    assert board.turn == (chess.WHITE if puzzle["colorOfUser"] == "white" else chess.BLACK)
    chosen_moves, matching = [], 0
    for ply, expected in enumerate(puzzle["solutionUci"]):
        if ply % 2:
            board.push_uci(expected)
            continue
        answer = engine.play(board, chess.engine.Limit(nodes=1), game=object(),
                             info=chess.engine.INFO_BASIC)
        move = answer.move
        if move is None or move not in board.legal_moves:
            raise RuntimeError(f"Maia returned invalid move {move}")
        chosen_moves.append(move.uci())
        if move.uci() != expected:
            return False, matching, chosen_moves
        matching += 1
        board.push(move)
    return True, matching, chosen_moves


def checkpoint(state, expected_count, message=""):
    hist = Counter()
    for row in RECORDS:
        index = 50 * (int(row["rating"]) // 50)
        hist[(index, "attempt")] += 1
        hist[(index, "solved")] += int(row["solved"])
    stats = {"state": state, "shard": SHARD, "shards": SHARDS,
             "attempted": len(RECORDS), "total": expected_count,
             "solved": sum(int(x["solved"]) for x in RECORDS),
             "failed": sum(not x["solved"] for x in RECORDS),
             "model": "Maia3-79M", "elo": 2600, "self_elo": 2600,
             "oppo_elo": 2600, "nodes": 1, "temperature": 0,
             "rating_min": 2000, "glicko_scale": 400,
             "message": message, "timestamp_utc": time.time(),
             "histogram": [[k, hist[(k, "solved")], hist[(k, "attempt")]]
                            for k in sorted({q[0] for q in hist})],
             "recent": RECORDS[-10:]}
    STATUS.write_text(json.dumps(stats, separators=(",", ":")), encoding="utf-8")
    with gzip.open(JOURNAL, "wt", encoding="utf-8", compresslevel=5) as output:
        for row in RECORDS:
            output.write(json.dumps(row, separators=(",", ":")) + "\n")
    command("git", "add", str(STATUS), str(JOURNAL))
    staged = command("git", "diff", "--cached", "--quiet", check=False)
    if staged.returncode:
        command("git", "commit", "-m", f"Maia3 shard {SHARD}: {len(RECORDS)}/{expected_count} ({state})")
        for trial in range(5):
            result = command("git", "push", "origin", f"HEAD:refs/heads/{BRANCH}", check=False)
            if result.returncode == 0:
                break
            if trial == 4:
                raise RuntimeError("Live checkpoint upload failed: " + result.stderr[-700:])
            time.sleep(5 * (trial + 1))
    print("CHECKPOINT", SHARD, len(RECORDS), expected_count, state, flush=True)


def main():
    setup_branch()
    with gzip.open("puzzles_2000plus.jsonl.gz", "rt", encoding="utf-8") as f:
        puzzles = [(i, json.loads(line)) for i, line in enumerate(f) if i % SHARDS == SHARD]
    total = len(puzzles)
    assert total > 0
    assert len(RECORDS) <= total
    for j, prev in enumerate(RECORDS):
        assert prev["index"] == puzzles[j][0] and prev["id"] == puzzles[j][1]["id"]
    if len(RECORDS) == total:
        checkpoint("completed", total, "Already complete")
        return
    checkpoint("loading", total, "Model startup")
    engine = start_engine()
    t0 = time.monotonic()
    try:
        for j in range(len(RECORDS), total):
            index, puzzle = puzzles[j]
            started = time.monotonic()
            for attempt in range(3):
                try:
                    solved, count, chosen = assess(engine, puzzle)
                    break
                except Exception as exc:
                    print("RETRY", index, attempt + 1, repr(exc), flush=True)
                    try:
                        engine.quit()
                    except Exception:
                        engine.close()
                    if attempt == 2:
                        raise
                    engine = start_engine()
            RECORDS.append({"index": index, "id": puzzle["id"], "rating": puzzle["rating"],
                            "solved": bool(solved), "matching_moves": count,
                            "required_moves": (len(puzzle["solutionUci"]) + 1) // 2,
                            "chosen": chosen, "seconds": round(time.monotonic() - started, 3)})
            if (j + 1) % 15 == 0 or time.monotonic() - t0 > 100 or j + 1 == total:
                checkpoint("running" if j + 1 < total else "completed", total)
                t0 = time.monotonic()
            if (j + 1) % 10 == 0:
                print("PUZZLE_PROGRESS", SHARD, j + 1, "/", total, "solved",
                      sum(bool(x["solved"]) for x in RECORDS), flush=True)
    except BaseException as exc:
        checkpoint("error", total, repr(exc))
        raise
    finally:
        try:
            engine.quit()
        except Exception:
            engine.close()
    Path(f"result-part-{SHARD:02d}.jsonl.gz").write_bytes(JOURNAL.read_bytes())


if __name__ == "__main__":
    main()
