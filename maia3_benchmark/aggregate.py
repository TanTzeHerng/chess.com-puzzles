"""Merge independently scored Maia3 shards into one exact serial Glicko-1 replay."""
import gzip
import json
import math
import subprocess
from collections import Counter
from pathlib import Path


def cmd(*argv, check=True):
    return subprocess.run(argv, check=check, text=True, capture_output=True)


def main():
    result_files = sorted(Path(".").glob("result-part-*.jsonl.gz"))
    assert len(result_files) == 64, f"Expected 64 shard files; received {len(result_files)}"
    all_rows = []
    for path in result_files:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            all_rows.extend(json.loads(line) for line in f if line.strip())
    with gzip.open("puzzles_2000plus.jsonl.gz", "rt", encoding="utf-8") as f:
        puzzles = [json.loads(line) for line in f if line.strip()]
    all_rows.sort(key=lambda x: x["index"])
    assert len(all_rows) == len(puzzles)
    for i, (a, p) in enumerate(zip(all_rows, puzzles)):
        assert a["index"] == i and a["id"] == p["id"] and a["rating"] == p["rating"]
    rating, rd = 2000.0, 350.0
    q = math.log(10.0) / 400.0
    solved = 0
    for row in all_rows:
        expectation = 1.0 / (1.0 + 10.0 ** ((row["rating"] - rating) / 400.0))
        precision = 1.0 / (rd * rd) + q * q * expectation * (1.0 - expectation)
        new_rd_sq = 1.0 / precision
        rating += q * new_rd_sq * (int(row["solved"]) - expectation)
        rd = math.sqrt(new_rd_sq)
        solved += int(row["solved"])
    summary = {"state": "completed", "model": "Maia3-79M",
               "Elo": 2600, "SelfElo": 2600, "OppoElo": 2600,
               "nodes_per_solver_move": 1, "temperature": 0, "top_p": 1,
               "total": len(all_rows), "solved": solved, "failed": len(all_rows)-solved,
               "scoring": "full Chess.com recorded solution only",
               "rating_system": "Glicko-1", "rating_scale": 400,
               "initial_rating": 2000, "initial_rd": 350,
               "puzzle_rd": 0, "rd_inflation": 0,
               "rating": rating, "rd": rd,
               "dataset": json.loads(Path("dataset_info.json").read_text())}
    Path("final_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with gzip.open("maia3-79m-complete-results.jsonl.gz", "wt", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    print("FINAL", json.dumps(summary), flush=True)
    branch = "maia3-79m-puzzle2000-final"
    cmd("git", "config", "user.name", "maia3-benchmark-bot")
    cmd("git", "config", "user.email", "maia3-benchmark-bot@users.noreply.github.com")
    remote = cmd("git", "ls-remote", "--exit-code", "--heads", "origin", branch, check=False)
    if remote.returncode == 0:
        cmd("git", "fetch", "origin", branch)
        cmd("git", "checkout", "-B", branch, "FETCH_HEAD")
    else:
        cmd("git", "checkout", "-b", branch)
    dest = Path("maia3_final")
    dest.mkdir(exist_ok=True)
    (dest / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    cmd("git", "add", str(dest / "summary.json"))
    cmd("git", "commit", "-m", "Maia3-79M completed >=2000 puzzle benchmark")
    cmd("git", "push", "origin", f"HEAD:refs/heads/{branch}")


if __name__ == "__main__":
    main()
