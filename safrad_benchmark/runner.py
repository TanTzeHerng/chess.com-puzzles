"""Safrad 2.1 benchmark. Windows GitHub Actions; progress is published independently of Actions logs."""
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import gzip
import datetime as dt
import io
import json
import os
import queue
import re
import subprocess
import threading
import time
import traceback
import zipfile
from pathlib import Path

import chess
import psutil
import requests

ROOT = Path(__file__).resolve().parent
ENGINE_DIR = ROOT / "safrad_engine"
DATA_DIR = ROOT / "download"
REPO = os.environ.get("GITHUB_REPOSITORY", "TanTzeHerng/chess.com-puzzles")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
SHARD = int(os.environ.get("SAFRAD_SHARD", "0"))
SHARDS = int(os.environ.get("SAFRAD_SHARDS", "4"))
TARGET_SECONDS = 600.0
SOFT_DEADLINE = time.monotonic() + (5 * 3600 + 15 * 60)
CHECKPOINT_PATH = f"safrad_benchmark/progress/shard-{SHARD:02d}.json"
GH_API = f"https://api.github.com/repos/{REPO}/contents/{CHECKPOINT_PATH}"
DATA_URL = "https://github.com/IchNukeDichWeg/chess.com-puzzles/releases/download/v2/puzzles-csv.zip"
ENGINE_URL = "https://sx.rosada.cz/projects/safrad-2.1/zip"
TCN = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?{~}(^)[_]@#$"
lock = threading.RLock()
stop_heartbeat = threading.Event()
http = requests.Session()
http.headers.update({"User-Agent": "Safrad-2.1-Chess-Puzzle-Benchmark/1.0"})
if TOKEN:
    http.headers.update({"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
state = {
    "schema_version": 1, "engine": "Safrad 2.1.35.210", "shard": SHARD, "shards": SHARDS,
    "target_seconds_per_solver_move": TARGET_SECONDS,
    "status": "initializing", "results": [], "workers": {},
    "worker_count": 0, "worker_calibration": [],
    "dataset_total_2500plus": None, "assigned_puzzles": None,
    "checkpoint_note": "In-progress info is as reported by Safrad; absent fields are not inferred.",
}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def log(*values):
    print(now(), *values, flush=True)

def update(**kwargs):
    with lock:
        state.update(kwargs)

def snapshot():
    with lock:
        data = json.loads(json.dumps(state, default=str))
    data["heartbeat_utc"] = now()
    data["runner_id"] = os.environ.get("GITHUB_RUN_ID")
    data["runner_attempt"] = os.environ.get("GITHUB_RUN_ATTEMPT")
    all_results = data["results"]
    data["completed_count"] = len(all_results)
    # Keep the GitHub checkpoint small and readable with hundreds of active workers.
    if len(all_results) > 50:
        data["compressed_results_gzip_b64"] = base64.b64encode(
            gzip.compress(json.dumps(all_results, separators=(",", ":")).encode("utf-8"), compresslevel=6)
        ).decode("ascii")
        data["results"] = all_results[-50:]
    for w in data["workers"].values():
        info = w.get("analysis") or {}
        if info:
            info["raw_tail"] = info.get("raw_tail", [])[-2:]
            if info.get("last_info"):
                info["last_info"] = info["last_info"][-500:]
    data["workers_active"] = sum(v.get("state")=="searching" for v in data["workers"].values())
    return data

def gh_get():
    r = http.get(GH_API, params={"ref": "main"}, timeout=30)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    j = r.json()
    return json.loads(base64.b64decode(j["content"])), j["sha"]

def gh_save(data):
    # One file per shard; Actions logs are not used as a progress mechanism.
    payload = base64.b64encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).decode()
    err = None
    for retry in range(4):
        try:
            _, sha = gh_get()
            body = {
                "message": f"Safrad 2.1 shard {SHARD} progress: {data.get('completed_count', 0)} completed",
                "content": payload, "branch": "main"
            }
            if sha:
                body["sha"] = sha
            r = http.put(GH_API, json=body, timeout=45)
            r.raise_for_status()
            return True
        except Exception as exc:
            err = repr(exc)
            log("CHECKPOINT_PUBLISH_ERROR", retry, err)
            time.sleep(min(2**retry, 10))
    raise RuntimeError("Could not publish GitHub checkpoint: " + str(err))

def publish():
    data = snapshot()
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    (DATA_DIR / f"shard-{SHARD:02d}-last-local.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    gh_save(data)

def heartbeat():
    while not stop_heartbeat.is_set():
        try:
            publish()
        except Exception as exc:
            log("HEARTBEAT_ERROR", repr(exc))
        stop_heartbeat.wait(45)

def download(url, dest):
    if dest.exists() and dest.stat().st_size > 100_000 and zipfile.is_zipfile(dest):
        return dest
    dest.parent.mkdir(parents=True,exist_ok=True)
    temp = dest.with_suffix(".tmp")
    with requests.get(url, stream=True, timeout=(25,180), headers={"User-Agent":"Mozilla/5.0"}) as response:
        response.raise_for_status()
        with temp.open("wb") as out:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    out.write(chunk)
    if not zipfile.is_zipfile(temp):
        raise RuntimeError("Downloaded data is not a ZIP archive: " + url + ", bytes=" + str(temp.stat().st_size))
    temp.replace(dest)
    return dest

def engine_setup():
    update(status="downloading_safrad", engine_url=ENGINE_URL)
    archive = download(ENGINE_URL, DATA_DIR / "safrad21.zip")
    ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        valid = [i for i in z.infolist() if not i.is_dir() and not any(p==".." for p in Path(i.filename).parts)]
        exes = []
        for info in valid:
            target = ENGINE_DIR / info.filename.replace("/", os.sep)
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as source, target.open("wb") as sink:
                import shutil
                shutil.copyfileobj(source, sink)
            if target.suffix.lower()==".exe":
                exes.append(target)
    if not exes:
        raise RuntimeError("Safrad archive contains no Windows executable")
    exes.sort(key=lambda p: (0 if "safrad" in p.name.lower() else 1, len(p.name)))
    update(engine_executable=str(exes[0]), engine_executables=[p.name for p in exes])
    return exes[0]

def decode(tcn):
    if len(tcn)%2:
        raise ValueError("Odd-length TCN encoding")
    moves=[]
    for i in range(0,len(tcn),2):
        a=TCN.index(tcn[i]); b=TCN.index(tcn[i+1]); promo=""
        if b>63:
            promo="qnrbk"[(b-64)//3]
            b=a+(-8 if a<16 else 8)+(b-64)%3-1
        moves.append(chr(97+a%8)+str(a//8+1)+chr(97+b%8)+str(b//8+1)+promo)
    return moves

def load_puzzles():
    update(status="downloading_chesscom_dataset", dataset_source=DATA_URL)
    archive = download(DATA_URL, DATA_DIR / "chesscom_puzzles_csv_v2.zip")
    with zipfile.ZipFile(archive) as z:
        files = sorted([n for n in z.namelist() if n.lower().endswith(".csv")],key=len)
        if not files:
            raise RuntimeError("Chess.com ZIP has no CSV")
        puzzles=[]
        with z.open(files[0]) as f:
            csv.field_size_limit(100000000)
            reader=csv.DictReader(io.TextIOWrapper(f,encoding="utf-8-sig",newline=""))
            for rec in reader:
                try:
                    rating=int(float(rec["rating"]))
                    if rating<2500:
                        continue
                    pid=int(rec["id"])
                    seq=decode(rec["tcnMoveList"])
                    if len(seq)<2:
                        continue
                    board=chess.Board(rec["initialFen"])
                    setup_move=chess.Move.from_uci(seq[0])
                    if setup_move not in board.legal_moves:
                        raise ValueError("illegal setup")
                    board.push(setup_move)
                    # Validate recorded line; do not silently invent puzzle moves.
                    for move in seq[1:]:
                        cm=chess.Move.from_uci(move)
                        if cm not in board.legal_moves:
                            raise ValueError("illegal line move "+move)
                        board.push(cm)
                    puzzles.append({"id":pid,"rating":rating,"initial_fen":rec["initialFen"],
                                    "uci_moves":seq})
                except Exception as exc:
                    log("INVALID_PUZZLE",rec.get("id"),repr(exc))
        puzzles.sort(key=lambda x:x["id"])
        unique={p["id"]:p for p in puzzles}
        puzzles=list(unique.values())
        puzzles.sort(key=lambda x:x["id"])
    update(dataset_total_2500plus=len(puzzles),assigned_puzzles=sum(i%SHARDS==SHARD for i in range(len(puzzles))),
           status="dataset_ready")
    if len(puzzles)!=19492:
        raise RuntimeError(f"Unexpected 2500+ dataset size: {len(puzzles)} (expected 19492)")
    return [p for i,p in enumerate(puzzles) if i%SHARDS==SHARD]

class Engine:
    def __init__(self, path):
        self.path=path
        self.proc=subprocess.Popen([str(path)],cwd=str(path.parent),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL,bufsize=0,
                                   creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.lines=queue.Queue()
        self.alive=True
        def reader():
            try:
                while True:
                    line=self.proc.stdout.readline()
                    if not line: break
                    self.lines.put((time.monotonic(),line.decode("utf-8","replace").strip()))
            except Exception as exc:
                self.lines.put((time.monotonic(),"read_error: "+repr(exc)))
        threading.Thread(target=reader,daemon=True).start()
        self.send("uci")
        self.until("uciok",12)
        self.send("isready")
        self.until("readyok",12)

    def send(self, cmd):
        if self.proc.poll() is not None:
            raise RuntimeError("Safrad exited code "+str(self.proc.returncode))
        self.proc.stdin.write((cmd+"\n").encode("ascii")); self.proc.stdin.flush()

    def until(self, wanted, seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("Safrad exited, code "+str(self.proc.returncode))
            try:
                t,s=self.lines.get(timeout=0.25)
            except queue.Empty:
                continue
            if s.strip()==wanted:
                return
        raise TimeoutError("Safrad timed out waiting for "+wanted)

    def close(self):
        try:
            self.send("quit")
            self.proc.wait(timeout=2)
        except Exception:
            try:self.proc.kill()
            except Exception:pass
        try:self.proc.wait(timeout=3)
        except Exception:pass

    def analyze(self, board, worker_id, requested_s, preliminary=False):
        self.send("ucinewgame")
        self.send("position fen "+board.fen())
        self.send("go infinite")
        start=time.monotonic()
        info={"last_info":None,"raw_tail":[],"depth":None,"nodes":None,"score":None,"pv":None}
        stopped=False
        while True:
            elapsed=time.monotonic()-start
            if self.proc.poll() is not None:
                raise RuntimeError("Safrad exited during search code="+str(self.proc.returncode))
            if elapsed>=requested_s and not stopped:
                self.send("stop"); stopped=True
            if stopped and elapsed>requested_s+12:
                raise TimeoutError("Safrad did not output bestmove after stop")
            try:
                t,line=self.lines.get(timeout=0.4)
            except queue.Empty:
                line=None
            if line:
                if line.startswith("info "):
                    info["last_info"]=line[-750:]
                    info["raw_tail"]=(info["raw_tail"]+[line[-500:]])[-12:]
                    for name,regex in [("depth",r"\bdepth\s+(\d+)"),
                                       ("nodes",r"\bnodes\s+(\d+)"),
                                       ("score",r"\bscore\s+(?:cp|mate)\s+(-?\d+)"),
                                       ("pv",r"\bpv\s+(.+)$")]:
                        m=re.search(regex,line)
                        if m:info[name]=m.group(1)
                if line.startswith("bestmove"):
                    actual=round(t-start,3)
                    move=line.split()[1] if len(line.split())>=2 else "(missing)"
                    if not preliminary:
                        with lock:
                            state["workers"][str(worker_id)] = {
                                **state["workers"].get(str(worker_id),{}),
                                "state":"move_returned","last_move":move,
                                "elapsed_seconds":actual,"analysis":info,
                            }
                    return {"move":move,"elapsed_seconds":actual,"early_return":actual<requested_s-2,
                            "analysis":info}
            if not preliminary:
                with lock:
                    w=state["workers"].setdefault(str(worker_id),{})
                    w.update({"state":"searching","search_elapsed_seconds":round(elapsed,1),
                              "analysis":info,"last_update_utc":now(),
                              "remaining_seconds":max(0,round(requested_s-elapsed,1))})

def probe_engine(path, board):
    e=Engine(path)
    try:
        t=time.monotonic()
        r=e.analyze(board,"preflight",7,preliminary=True)
        if r["early_return"]:
            raise RuntimeError("Engine ends early even with go infinite: "+str(r))
        return {"bestmove":r["move"],"info_seen":bool(r["analysis"]["last_info"]),
                "preflight_seconds":round(time.monotonic()-t,2)}
    finally:
        e.close()

def calibrate_workers(path, board):
    # Stress actual active searchers, monitor RAM, process life and responsiveness.
    # Deliberately no os.cpu_count / core-count based limit.
    update(status="calibrating_workers",worker_calibration=[])
    baseline=psutil.virtual_memory().available
    safety_floor=max(int(psutil.virtual_memory().total*.14),700*1024*1024)
    engines=[]
    results=[]
    targets=[1,2,4,8,16,32,64,128]  # immediate active-search benchmark using previous stable 128-per-runner checkpoint; avoid 256+ startup stall
    best=0
    try:
        for target in targets:
            if time.monotonic()>SOFT_DEADLINE-900:break
            update(calibration_target=target, calibration_live_launched=len(engines))
            # Predict memory headroom based on measured running instances.
            rss=sum(psutil.Process(e.proc.pid).memory_info().rss for e in engines if e.proc.poll() is None)
            if engines and rss:
                average=rss/len(engines)
                predicted_free=psutil.virtual_memory().available-int((target-len(engines))*average*1.3)
                if predicted_free<safety_floor:
                    results.append({"target":target,"stable":False,"reason":"predicted_memory_pressure"})
                    break
            try:
                # Launch the next cohort concurrently. Serial UCI handshakes
                # become very slow once many previous engines are searching.
                def launch_probe(_):
                    e=Engine(path)
                    try:
                        e.send("position fen "+board.fen())
                        e.send("go infinite")
                        return e
                    except Exception:
                        e.close()
                        raise
                failures=[]
                new_count=target-len(engines)
                with ThreadPoolExecutor(max_workers=min(24,new_count)) as pool:
                    futures=[pool.submit(launch_probe, i) for i in range(new_count)]
                    for future in as_completed(futures):
                        try:
                            engines.append(future.result())
                        except Exception as exc:
                            failures.append(repr(exc))
                        update(calibration_live_launched=len(engines))
                if failures:
                    raise RuntimeError("probe_launch_failures: "+str(failures[:3]))
                if psutil.virtual_memory().available<safety_floor:
                    raise MemoryError("low_available_memory")
                started=time.monotonic()
                while time.monotonic()-started<12:
                    if any(e.proc.poll() is not None for e in engines):
                        raise RuntimeError("calibration_engine_exited")
                    if psutil.virtual_memory().available<safety_floor:
                        raise MemoryError("memory_below_safety_floor")
                    time.sleep(0.5)
                best=len(engines)
                point={"target":target,"stable":True,"available_ram_mb":round(psutil.virtual_memory().available/1048576),
                       "engine_rss_total_mb":round(sum(psutil.Process(e.proc.pid).memory_info().rss for e in engines)/1048576)}
                results.append(point)
                update(worker_calibration=results, calibrated_stable_workers=best)
                log("CALIBRATION",point)
            except Exception as exc:
                results.append({"target":target,"stable":False,"reason":repr(exc)})
                update(worker_calibration=results)
                break
        if best==0:
            raise RuntimeError("Cannot sustain a single Safrad engine")
        # A longer soak at the largest empirically stable count.
        end=time.monotonic()+45
        while time.monotonic()<end:
            if sum(e.proc.poll() is None for e in engines)<best:
                raise RuntimeError("Calibration worker died during final soak")
            if psutil.virtual_memory().available<safety_floor:
                raise MemoryError("Calibration memory pressure during soak")
            time.sleep(1)
        return best
    finally:
        # Stop stress-test engines as a group; sequential 2-second waits would
        # waste many minutes when hundreds of engines are under CPU pressure.
        for e in engines:
            try: e.send("stop")
            except Exception: pass
        for e in engines:
            try: e.proc.kill()
            except Exception: pass
        for e in engines:
            try: e.proc.wait(timeout=1)
            except Exception: pass

def solve_one(e,p,worker_id):
    board=chess.Board(p["initial_fen"])
    seq=p["uci_moves"]
    board.push_uci(seq[0])
    moves=[]
    correct=True
    technical_error=None
    for index in range(1,len(seq),2):
        expected=seq[index]
        with lock:
            state["workers"][str(worker_id)]={
                "state":"searching","puzzle_id":p["id"],"puzzle_rating":p["rating"],
                "solver_move_number":(index+1)//2,"expected_solution_move":expected,
                "fen":board.fen(),"search_elapsed_seconds":0,"analysis":{},
                "last_update_utc":now(),
            }
        try:
            ans=e.analyze(board,worker_id,TARGET_SECONDS)
            correct_move=(ans["move"]==expected)
            moves.append({"expected":expected,"actual":ans["move"],
                          "correct":correct_move,"seconds":ans["elapsed_seconds"],
                          "returned_early":ans["early_return"],"analysis":ans["analysis"]})
            if ans["early_return"]:
                technical_error="Safrad terminated its infinite search before 600 seconds"
                correct=None
                break
            if not correct_move:
                correct=False
                break
            board.push_uci(expected)
            if index+1<len(seq):
                board.push_uci(seq[index+1])
        except Exception as exc:
            technical_error=repr(exc)
            correct=None
            break
    return {"id":p["id"],"rating":p["rating"],"solved":correct,
            "technical_error":technical_error, "moves":moves,
            "finished_utc":now()}

def main():
    # Verify independent checkpoint visibility before expensive work begins.
    prev,_=gh_get()
    if prev and prev.get("schema_version")==1 and prev.get("shard")==SHARD and prev.get("shards")==SHARDS:
        if prev.get("compressed_results_gzip_b64"):
            state["results"] = json.loads(gzip.decompress(base64.b64decode(
                prev["compressed_results_gzip_b64"])).decode("utf-8"))
        else:
            state["results"] = prev.get("results",[])
        log("RESUME",len(state["results"]))
    state["started_utc"]=now()
    publish()
    thread=threading.Thread(target=heartbeat,daemon=True)
    thread.start()
    exe=engine_setup()
    update(status="validating_engine")
    # Initial position preflight; full puzzle preflight below.
    pre=probe_engine(exe,chess.Board())
    update(protocol_preflight=pre)
    puzzles=load_puzzles()
    if not puzzles:
        update(status="no_puzzles")
        return
    board=chess.Board(puzzles[0]["initial_fen"])
    board.push_uci(puzzles[0]["uci_moves"][0])
    pre=probe_engine(exe,board)
    update(puzzle_preflight=pre)
    count=calibrate_workers(exe,board)
    update(status="benchmark_running",worker_count=count)
    publish()
    completed={r["id"] for r in state["results"] if r.get("technical_error") is None}
    pending=queue.Queue()
    for p in puzzles:
        if p["id"] not in completed:
            pending.put(p)
    update(remaining_count=pending.qsize())
    fatal=[]
    def worker(i):
        e=None
        try:
            e=Engine(exe)
            while time.monotonic()<SOFT_DEADLINE-TARGET_SECONDS-45:
                try:p=pending.get_nowait()
                except queue.Empty:break
                with lock: state["workers"][str(i)]={"state":"starting","puzzle_id":p["id"],"last_update_utc":now()}
                result=solve_one(e,p,i)
                if result["technical_error"]:
                    # Don't count technical failures, replay them on subsequent run.
                    fatal.append({"worker":i,"puzzle_id":p["id"],"error":result["technical_error"]})
                    pending.put(p)
                    with lock:state["workers"][str(i)]={"state":"technical_error","puzzle_id":p["id"],
                                                        "error":result["technical_error"],"last_update_utc":now()}
                    break
                else:
                    with lock:
                        state["results"].append(result)
                        state["remaining_count"]=pending.qsize()
                        state["workers"][str(i)]={"state":"puzzle_done","puzzle_id":p["id"],
                            "solved":result["solved"],"last_update_utc":now()}
                pending.task_done()
        except Exception as exc:
            fatal.append({"worker":i,"error":repr(exc)})
            with lock:state["workers"][str(i)]={"state":"failed","error":repr(exc)}
        finally:
            if e:e.close()
    threads=[threading.Thread(target=worker,args=(i,),daemon=True) for i in range(count)]
    for t in threads:t.start()
    for t in threads:t.join()
    update(status="shard_completed" if pending.empty() else "awaiting_next_scheduled_run",
           errors=fatal[-30:], remaining_count=pending.qsize(),ended_utc=now())
    publish()

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        update(status="fatal_error",error=repr(exc),traceback=traceback.format_exc()[-5000:])
        try:publish()
        except Exception as error:log("FINAL_PUBLISH_ERROR",repr(error))
        raise
    finally:
        stop_heartbeat.set()
