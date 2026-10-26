"""Single Safrad 2.1 NPS test, one native Windows engine process on a separate GitHub runner."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import subprocess
import sys
import threading
import time
import zipfile

import psutil
import requests

BASE=Path(__file__).resolve().parent
RUNNER_LABEL=os.environ.get("SAFRAD_COMPARISON_RUNNER","unknown")
import shutil
if shutil.which("wine") is None:
    raise RuntimeError("Wine executable is not installed on this Linux runner")
ENGINE_DIR=BASE/("compare_engine_"+RUNNER_LABEL)
RESULTS=BASE/"nps"
RESULTS.mkdir(parents=True,exist_ok=True)
LOCAL=RESULTS/("compare-"+RUNNER_LABEL+".json")
REPO=os.environ.get("GITHUB_REPOSITORY","TanTzeHerng/chess.com-puzzles")
TOKEN=os.environ.get("GITHUB_TOKEN","")
GITHUB_PATH="safrad_benchmark/nps/compare-"+RUNNER_LABEL+".json"
API="https://api.github.com/repos/"+REPO+"/contents/"+GITHUB_PATH
DOWNLOAD="https://sx.rosada.cz/projects/safrad-2.1/zip"
FEN="2r4k/5p1p/3pb3/pP1Np3/P1BNPp1q/3Q1P2/6KP/R7 b - - 0 2"
TARGET=float(os.environ.get("SAFRAD_COMPARISON_SECONDS","120"))
state={"schema_version":1,"kind":"one-worker-runner-comparison","runner_label":RUNNER_LABEL,"status":"initializing",
       "engine":"Safrad 2.1.35.210","engine_url":DOWNLOAD,
       "benchmark_fen":FEN,"comparison_puzzle_id":802,
       "target_seconds":TARGET,"worker_count":1,"search_workers":0,
       "runner_id":os.environ.get("GITHUB_RUN_ID"),
       "started_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
       "host_os":platform.platform(),"processor":platform.processor(),
       "architecture":platform.machine(),
       "os_cpu_count":os.cpu_count(),"psutil_logical_cpus":psutil.cpu_count(),
       "samples":[]}
session=requests.Session()
session.headers.update({"Authorization":"Bearer "+TOKEN,
                        "Accept":"application/vnd.github+json",
                        "X-GitHub-Api-Version":"2022-11-28",
                        "User-Agent":"Safrad-single-worker-nps"})
def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()
def publish():
    state["heartbeat_utc"]=timestamp()
    LOCAL.write_text(json.dumps(state,indent=2),encoding="utf-8")
    if not TOKEN:
        return
    raw=json.dumps(state,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    import base64
    encoded=base64.b64encode(raw).decode("ascii")
    for attempt in range(4):
        try:
            get=session.get(API,timeout=25)
            if get.status_code==404:
                sha=None
            else:
                get.raise_for_status()
                sha=get.json()["sha"]
            body={"message":"Safrad solo NPS: "+str(round(state.get("elapsed_seconds",0)))+" seconds",
                  "branch":"main","content":encoded}
            if sha:body["sha"]=sha
            put=session.put(API,json=body,timeout=35)
            put.raise_for_status()
            return
        except Exception as exc:
            print("PUBLISH_ERROR",repr(exc),flush=True)
            time.sleep(attempt+1)
    raise RuntimeError("Failed to publish standalone NPS status to GitHub")
def setup_engine():
    state["status"]="downloading_engine"
    publish()
    ENGINE_DIR.mkdir(parents=True,exist_ok=True)
    zipname=ENGINE_DIR/"safrad-2.1.zip"
    with requests.get(DOWNLOAD,stream=True,timeout=90) as response:
        response.raise_for_status()
        with zipname.open("wb") as dest:
            for chunk in response.iter_content(65536):
                if chunk:dest.write(chunk)
    if not zipfile.is_zipfile(zipname):
        raise RuntimeError("Official engine ZIP download invalid")
    with zipfile.ZipFile(zipname) as z:
        z.extractall(ENGINE_DIR)
    exes=sorted((p for p in ENGINE_DIR.rglob("*.exe") if p.is_file()),
                key=lambda p:(0 if "safrad" in p.name.lower() else 1,len(p.name)))
    if not exes:raise RuntimeError("Official ZIP contains no engine EXE")
    p=exes[0]
    state["engine_executable"]=p.name
    state["engine_sha256"]=hashlib.sha256(p.read_bytes()).hexdigest()
    if state["engine_sha256"]!="205556a25d8f201c642102e026c4dc778204b51aa29292ebd623faf9bd2d8d74":
        raise RuntimeError("Safrad executable hash does not match reference baseline")
    return p
def run_engine(path):
    state["status"]="starting_one_worker"
    state["emulation"]="Wine (original Safrad Windows EXE)"
    state["wine_version"]=subprocess.check_output(["wine","--version"],text=True,timeout=10).strip()
    try:
        cp=subprocess.check_output(["bash","-lc","lscpu | grep \"Model name\" | head -1"],timeout=12,text=True)
        state["cpu_model"]=cp.strip()[:200]
    except Exception as exc:
        state["cpu_model_error"]=repr(exc)
    publish()
    proc=subprocess.Popen(["wine",str(path)],cwd=str(path.parent),stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,
                          creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    ps=psutil.Process(proc.pid)
    q=queue.Queue()
    def feed():
        while True:
            line=proc.stdout.readline()
            if not line:break
            q.put((time.monotonic(),line.decode("utf-8","replace").strip()))
    threading.Thread(target=feed,daemon=True).start()
    def send(message):
        proc.stdin.write((message+"\n").encode("ascii"))
        proc.stdin.flush()
    def await_token(token,limit=20):
        end=time.monotonic()+limit
        while time.monotonic()<end:
            if proc.poll() is not None:raise RuntimeError("Engine quit during UCI handshake")
            try:_,line=q.get(timeout=.2)
            except queue.Empty:continue
            if line==token:return
        raise TimeoutError("No "+token+" from engine")
    try:
        send("uci")
        await_token("uciok")
        send("isready")
        await_token("readyok")
        send("ucinewgame")
        send("position fen "+FEN)
        state["status"]="searching"
        state["search_workers"]=1
        state["engine_pid"]=proc.pid
        send("go infinite")
        started=time.monotonic()
        cpu_before=ps.cpu_times()
        basecpu=cpu_before.user+cpu_before.system
        last_published=started
        sent_stop=False
        reported_bestmove=None
        line_count=0
        nps_line_count=0
        last_progress={}
        while True:
            elapsed=time.monotonic()-started
            if elapsed>=TARGET and not sent_stop:
                send("stop")
                sent_stop=True
            if sent_stop and elapsed>TARGET+20:raise TimeoutError("No bestmove after stop")
            if proc.poll() is not None:
                raise RuntimeError("Safrad process terminated during search")
            try:received,line=q.get(timeout=.25)
            except queue.Empty:line=None
            if line:
                line_count+=1
                if line.startswith("info "):
                    nps_match=re.search(r"\bnps\s+(\d+)",line)
                    nodes_match=re.search(r"\bnodes\s+(\d+)",line)
                    time_match=re.search(r"\btime\s+(\d+)",line)
                    depth_match=re.search(r"\bdepth\s+(\d+)",line)
                    if nps_match:
                        nps_line_count+=1
                        last_progress={"nps":int(nps_match.group(1)),
                                       "nodes":int(nodes_match.group(1)) if nodes_match else None,
                                       "engine_reported_ms":int(time_match.group(1)) if time_match else None,
                                       "depth":int(depth_match.group(1)) if depth_match else last_progress.get("depth"),
                                       "last_info":line[-500:]}
                if line.startswith("bestmove"):
                    reported_bestmove=line.split()[1] if len(line.split())>1 else "(missing)"
                    state["returned_early"]=round(received-started,3)<TARGET-2
                    break
            elapsed=time.monotonic()-started
            if elapsed>=20 and (elapsed-(last_published-started)>=20):
                cp=ps.cpu_times()
                cpu_s=cp.user+cp.system-basecpu
                sample={"utc":timestamp(),"elapsed_seconds":round(elapsed,2),
                        "cpu_seconds":round(cpu_s,2),**last_progress}
                state["samples"].append(sample)
                state["elapsed_seconds"]=round(elapsed,2)
                state["search_cpu_seconds"]=round(cpu_s,2)
                state["last"]=last_progress.copy()
                state["uci_lines"]=line_count
                state["uci_nps_lines"]=nps_line_count
                print("LIVE_SAMPLE",json.dumps(sample),flush=True)
                publish()
                last_published=time.monotonic()
        elapsed=time.monotonic()-started
        cp=ps.cpu_times()
        cpu_s=cp.user+cp.system-basecpu
        state.update(status="completed",search_workers=0,
                     elapsed_seconds=round(elapsed,3),
                     search_cpu_seconds=round(cpu_s,3),
                     bestmove=reported_bestmove,
                     latest_nps=last_progress.get("nps"),
                     latest_nodes=last_progress.get("nodes"),
                     engine_reported_ms=last_progress.get("engine_reported_ms"),
                     search_nodes_per_cpu_second=round(last_progress.get("nodes",0)/cpu_s) if cpu_s>0 else None,
                     uci_lines=line_count,uci_nps_lines=nps_line_count,
                     ended_utc=timestamp())
        publish()
        print("FINAL_SOLO_NPS",json.dumps(state),flush=True)
    finally:
        try:
            if proc.poll() is None:send("quit")
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
if __name__=="__main__":
    try:
        exe=setup_engine()
        run_engine(exe)
    except Exception as error:
        state.update(status="error",error=repr(error),ended_utc=timestamp(),search_workers=0)
        publish()
        raise
