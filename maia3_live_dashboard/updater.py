"""Publish live Maia3-79M Glicko checkpoints. Runs remotely, never on user's PC."""
import concurrent.futures
import datetime as dt
import gzip
import json
import math
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "TanTzeHerng/chess.com-puzzles"
TARGET = "maia3-79m-puzzle2000-dashboard"
TOTAL = 81548
SHARDS = 64

def read_shard(i):
    branch=f"maia3-79m-puzzle2000-progress-{i:02d}"
    url=f"https://raw.githubusercontent.com/{REPO}/{branch}/maia3_live/results.jsonl.gz?v={int(time.time())}"
    req=urllib.request.Request(url,headers={"User-Agent":"Maia3PuzzleLiveDashboard/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            compressed=response.read()
        content=gzip.decompress(compressed).decode("utf-8")
        data=[json.loads(line) for line in content.splitlines() if line.strip()]
        assert len(data)<=1275
        for j,row in enumerate(data):
            assert row["index"]%SHARDS==i and row["index"]//SHARDS==j
            assert isinstance(row["rating"],int) and isinstance(row["solved"],bool)
        return i,data,None
    except urllib.error.HTTPError as exc:
        if exc.code==404:
            return i,[],f"Not published ({exc.code})"
        return i,[],repr(exc)
    except Exception as exc:
        return i,[],repr(exc)

with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
    shards=sorted(pool.map(read_shard,range(SHARDS)))
results=[row for _,data,_ in shards for row in data]
results.sort(key=lambda x:x["index"])
assert len(results)==len(set(row["index"] for row in results))
assert len(results)<=TOTAL
rating,rd=2000.,350.
q=math.log(10)/400
solved=0
for row in results:
    expected=1/(1+10**((row["rating"]-rating)/400))
    variance=1/(1/rd**2+q*q*expected*(1-expected))
    rating+=q*variance*(int(row["solved"])-expected)
    rd=math.sqrt(variance)
    solved+=int(row["solved"])
summary={
    "model":"Maia3-79M","Elo":2600,"SelfElo":2600,"OppoElo":2600,
    "nodes_per_move":1,"total":TOTAL,"attempted":len(results),
    "solved":solved,"failed":len(results)-solved,
    "solve_rate":solved/len(results) if results else None,
    "rating":rating,"rd":rd,"rating_system":"Glicko-1",
    "rating_scale":400,"starting_rating":2000,
    "is_final":len(results)==TOTAL,
    "published_shards":sum(bool(data) for _,data,_ in shards),
    "complete_shards":sum(len(data)==(TOTAL//SHARDS+(i<TOTAL%SHARDS)) for i,data,_ in shards),
    "missing_shards":[{"shard":i,"error":e} for i,data,e in shards if e],
    "last_updated_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
    "source_run":"https://github.com/"+REPO+"/actions/runs/39191728925"
}
print("LIVE_MAIA3_GLICKO",json.dumps(summary),flush=True)
def git(*args,check=True):
    return subprocess.run(("git",)+args,check=check,text=True,capture_output=True)
git("config","user.email","maia3-dashboard-bot@users.noreply.github.com")
git("config","user.name","Maia3 Dashboard")
git("fetch","--depth=1","origin",TARGET)
git("checkout","-B",TARGET,"FETCH_HEAD")
dest=Path("maia3_live_dashboard")/"progress.json"
dest.parent.mkdir(parents=True,exist_ok=True)
old=None
if dest.exists():
    try: old=json.loads(dest.read_text())
    except ValueError: pass
if old and old.get("attempted")==summary["attempted"] and old.get("solved")==summary["solved"] and old.get("is_final")==summary["is_final"]:
    print("UNCHANGED",flush=True)
else:
    dest.write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    git("add",str(dest))
    git("commit","-m",f"Update Maia3 Glicko {len(results)}/{TOTAL}")
    git("push","origin",f"HEAD:refs/heads/{TARGET}")
    print("PUBLISHED",flush=True)
