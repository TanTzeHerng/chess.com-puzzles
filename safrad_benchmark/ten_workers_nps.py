"""Run 10 independent Safrad 2.1 UCI processes concurrently, measuring each NPS.

One free Ubuntu runner with Wine, one original Windows executable, no engine-option changes.
"""
import base64, datetime as dt, hashlib, json, os, platform, queue, re, shutil
import subprocess, threading, time, zipfile
from pathlib import Path
import requests, psutil

COUNT=10
RUN_SECONDS=120.0
ZIP_URL="https://sx.rosada.cz/projects/safrad-2.1/zip"
EXPECTED_SHA="205556a25d8f201c642102e026c4dc778204b51aa29292ebd623faf9bd2d8d74"
FEN="2r4k/5p1p/3pb3/pP1Np3/P1BNPp1q/3Q1P2/6KP/R7 b - - 0 2"
ROOT=Path(__file__).resolve().parent
ENGINE_DIR=ROOT/"ten_workers_engine"
OUT=ROOT/"nps"/"ten-workers-concurrent.json"
OUT.parent.mkdir(parents=True,exist_ok=True)
REPO=os.environ.get("GITHUB_REPOSITORY","TanTzeHerng/chess.com-puzzles")
TOKEN=os.environ.get("GITHUB_TOKEN","")
URL=f"https://api.github.com/repos/{REPO}/contents/safrad_benchmark/nps/ten-workers-concurrent.json"
GH=requests.Session()
GH.headers.update({"Authorization":"Bearer "+TOKEN,"Accept":"application/vnd.github+json","User-Agent":"Safrad-10-worker-NPS"})
lock=threading.RLock()
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
state={"schema_version":1,"kind":"ten-concurrent-safrad-workers","status":"initializing",
       "engine":"Safrad 2.1.35.210","sha256_expected":EXPECTED_SHA,
       "settings_changed":False,"worker_count_requested":COUNT,"run_seconds":RUN_SECONDS,
       "position_fen":FEN,"host":platform.platform(),"architecture":platform.machine(),
       "logical_processors":os.cpu_count(),"workflow_run_id":os.environ.get("GITHUB_RUN_ID"),
       "workers":{str(i):{"status":"pending"} for i in range(COUNT)},
       "started_at_utc":now()}
def publish():
    with lock:
        data=json.loads(json.dumps(state))
    data["heartbeat_utc"]=now()
    data["workers_searching"]=sum(w.get("status")=="searching" for w in data["workers"].values())
    data["workers_finished"]=sum(w.get("status")=="completed" for w in data["workers"].values())
    data["workers_failed"]=sum(w.get("status")=="error" for w in data["workers"].values())
    data["workers_with_nps"]=sum(w.get("nps",0)>0 for w in data["workers"].values())
    valid=[w.get("nps") for w in data["workers"].values() if isinstance(w.get("nps"),int) and w["nps"]>0]
    data["total_nps_reported"]=sum(valid)
    data["average_nps_available"]=round(sum(valid)/len(valid)) if valid else None
    OUT.write_text(json.dumps(data,indent=2),encoding="utf-8")
    if not TOKEN:return
    encoded=base64.b64encode(json.dumps(data,separators=(",",":")).encode("utf-8")).decode("ascii")
    for attempt in range(5):
        try:
            r=GH.get(URL,timeout=25)
            if r.status_code==404:sha=None
            else:r.raise_for_status();sha=r.json()["sha"]
            req={"message":"10 Safrad workers: "+str(data["workers_with_nps"])+" reporting NPS",
                 "content":encoded,"branch":"main"}
            if sha:req["sha"]=sha
            put=GH.put(URL,json=req,timeout=35)
            put.raise_for_status()
            print("PUBLISHED",data["heartbeat_utc"],"reporting",data["workers_with_nps"],
                  "running",data["workers_searching"],flush=True)
            return
        except Exception as exc:
            print("PUBLISH_FAILED",attempt,repr(exc),flush=True)
            time.sleep(min(2**attempt,8))
    raise RuntimeError("Could not publish checkpoint to GitHub")
def update(i,**kws):
    with lock:state["workers"][str(i)].update(kws)
def setup():
    with lock:state["status"]="downloading_engine"
    publish()
    ENGINE_DIR.mkdir(parents=True,exist_ok=True)
    zpath=ENGINE_DIR/"safrad_original.zip"
    with requests.get(ZIP_URL,stream=True,timeout=100) as response:
        response.raise_for_status()
        with zpath.open("wb") as dest:
            for chunk in response.iter_content(65536):
                if chunk:dest.write(chunk)
    if not zipfile.is_zipfile(zpath):raise RuntimeError("Official Safrad download is not a ZIP file")
    with zipfile.ZipFile(zpath) as archive:archive.extractall(ENGINE_DIR)
    paths=sorted(ENGINE_DIR.rglob("*.exe"),key=lambda p:(0 if "safrad" in p.name.lower() else 1,len(p.name)))
    if not paths:raise RuntimeError("No Safrad EXE")
    exe=paths[0]
    real=hashlib.sha256(exe.read_bytes()).hexdigest()
    if real!=EXPECTED_SHA:raise RuntimeError("Engine hash mismatch: "+real)
    if not shutil.which("wine"):raise RuntimeError("Wine is missing")
    rawcpu=subprocess.run(["lscpu"],capture_output=True,text=True,timeout=15)
    lines=[ln.strip() for ln in rawcpu.stdout.splitlines() if any(x in ln for x in ("Model name:", "CPU(s):", "Architecture:"))]
    with lock:
        state["engine_sha256"]=real
        state["cpu_description"]=lines
        state["wine_version"]=subprocess.check_output(["wine","--version"],text=True,timeout=15).strip()
        state["engine_executable_name"]=exe.name
        state["status"]="starting_workers"
    publish()
    return exe
class Engine:
    def __init__(self,exe,idx):
        self.idx=idx
        self.proc=subprocess.Popen(["wine",str(exe)],cwd=str(exe.parent),
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL,bufsize=0)
        self.q=queue.Queue()
        self.lines_read=0
        def read():
            try:
                while True:
                    raw=self.proc.stdout.readline()
                    if not raw:break
                    self.q.put((time.monotonic(),raw.decode("utf-8","replace").strip()))
            except Exception as exc:self.q.put((time.monotonic(),"read_error: "+repr(exc)))
        threading.Thread(target=read,daemon=True).start()
        try:
            self.send("uci");self.wait("uciok",35)
            self.send("isready");self.wait("readyok",35)
        except Exception:
            self.close()
            raise
    def send(self,cmd):
        if self.proc.poll() is not None:raise RuntimeError("Safrad exited with code "+str(self.proc.returncode))
        self.proc.stdin.write((cmd+"\n").encode("ascii"))
        self.proc.stdin.flush()
    def wait(self,target,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if self.proc.poll() is not None:raise RuntimeError("Safrad exited during UCI handshake")
            try:_,line=self.q.get(timeout=.25)
            except queue.Empty:continue
            if line==target:return
        raise TimeoutError("Timed out waiting for "+target)
    def close(self):
        try:
            if self.proc.poll() is None:self.send("quit")
            self.proc.wait(timeout=2)
        except Exception:
            try:self.proc.kill();self.proc.wait(timeout=2)
            except Exception:pass
def main():
    exe=setup()
    engines=[None]*COUNT
    errors=[]
    def start(i):
        for attempt in range(3):
            try:
                e=Engine(exe,i)
                engines[i]=e
                update(i,status="ready",pid=e.proc.pid)
                print("READY",i,e.proc.pid,flush=True)
                return
            except Exception as ex:
                update(i,status="launch_retry",error=repr(ex),attempt=attempt+1)
                time.sleep(1+attempt*2)
        with lock:errors.append(i)
        update(i,status="error",error="Failed to start after three attempts")
    starter=[threading.Thread(target=start,args=(i,),daemon=True) for i in range(COUNT)]
    for t in starter:t.start()
    for t in starter:t.join()
    if errors:
        with lock:state["status"]="launch_failure"
        publish()
        for e in engines:
            if e:e.close()
        raise RuntimeError("Ten engines were not all ready: "+str(errors))
    # Do not begin timing until all ten independent UCI engines have initialized.
    for e in engines:
        e.send("ucinewgame")
        e.send("position fen "+FEN)
    begin=threading.Event()
    completed=[False]*COUNT
    def measure(i,e):
        try:
            begin.wait()
            e.send("go infinite")
            started=time.monotonic()
            update(i,status="searching",search_started_utc=now())
            last={"nps":None,"nodes":None,"depth":None,"engine_time_ms":None}
            stop_sent=False
            best=None
            while True:
                elapsed=time.monotonic()-started
                if elapsed>=RUN_SECONDS and not stop_sent:
                    e.send("stop");stop_sent=True
                if elapsed>RUN_SECONDS+20:raise TimeoutError("No bestmove after stop")
                if e.proc.poll() is not None:raise RuntimeError("Safrad exited while searching")
                try:
                    t,line=e.q.get(timeout=.15)
                except queue.Empty:continue
                if line.startswith("info "):
                    for field,pattern in [
                        ("nps",r"\bnps\s+(\d+)"),
                        ("nodes",r"\bnodes\s+(\d+)"),
                        ("depth",r"\bdepth\s+(\d+)"),
                        ("engine_time_ms",r"\btime\s+(\d+)"),
                    ]:
                        match=re.search(pattern,line)
                        if match:last[field]=int(match.group(1))
                    if last["nps"] and last["nodes"] is not None:
                        update(i,nps=last["nps"],nodes=last["nodes"],depth=last["depth"],
                               engine_time_ms=last["engine_time_ms"],
                               elapsed_seconds=round(time.monotonic()-started,2))
                if line.startswith("bestmove"):
                    best=line.split()[1] if len(line.split())>1 else "(missing)"
                    break
            elapsed=time.monotonic()-started
            update(i,status="completed",bestmove=best,elapsed_seconds=round(elapsed,3),
                   returned_early=elapsed<RUN_SECONDS-2,
                   **{key:val for key,val in last.items() if val is not None})
            completed[i]=True
        except Exception as exc:
            update(i,status="error",error=repr(exc),elapsed_seconds=round(time.monotonic()-started,2) if "started" in locals() else None)
        finally:
            e.close()
    threads=[threading.Thread(target=measure,args=(i,e),daemon=True) for i,e in enumerate(engines)]
    for t in threads:t.start()
    with lock:state["status"]="searching";state["all_ready_at_utc"]=now()
    begin.set()
    publish()
    while any(t.is_alive() for t in threads):
        time.sleep(10)
        publish()
    for t in threads:t.join()
    with lock:
        state["status"]="completed" if all(completed) else "partial_failure"
        state["finished_at_utc"]=now()
    publish()
    print("TEN_WORKER_RESULTS",json.dumps(state,default=str),flush=True)
    if not all(completed):raise RuntimeError("Some worker results incomplete")
if __name__=="__main__":
    try:main()
    except Exception as exc:
        with lock:
            state["status"]="fatal_error"
            state["error"]=repr(exc)
            state["finished_at_utc"]=now()
        try:publish()
        except Exception as publish_error:print("FINAL_PUBLISH_FAILURE",repr(publish_error),flush=True)
        raise
