"""Safrad 2.1 host-only NPS optimization. NO engine options, executable patches, or move-selection changes."""
import base64
import ctypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import subprocess
import threading
import time
import zipfile
import psutil
import requests

HERE=Path(__file__).resolve().parent
MODE=os.environ.get("SAFRAD_HOST_TEST_MODE","priority-affinity")
TARGET_HASH="205556a25d8f201c642102e026c4dc778204b51aa29292ebd623faf9bd2d8d74"
ENGINE_URL="https://sx.rosada.cz/projects/safrad-2.1/zip"
FEN="2r4k/5p1p/3pb3/pP1Np3/P1BNPp1q/3Q1P2/6KP/R7 b - - 0 2"
ROOT=HERE/("host_engine_"+MODE)
OUTPUT=HERE/"nps"/("host-opt-"+MODE+".json")
OUTPUT.parent.mkdir(exist_ok=True,parents=True)
GH_REPO=os.environ.get("GITHUB_REPOSITORY","TanTzeHerng/chess.com-puzzles")
TOKEN=os.environ.get("GITHUB_TOKEN","")
API=f"https://api.github.com/repos/{GH_REPO}/contents/safrad_benchmark/nps/host-opt-{MODE}.json"
HTTP=requests.Session()
HTTP.headers.update({"Authorization":"Bearer "+TOKEN,"User-Agent":"Safrad host-only NPS test","Accept":"application/vnd.github+json"})
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
state={"schema_version":1,"engine":"Safrad 2.1.35.210","engine_sha256":TARGET_HASH,
       "one_worker":True,"engine_settings_unchanged":True,
       "fen":FEN,"mode":MODE,"status":"initializing","runner_id":os.environ.get("GITHUB_RUN_ID"),
       "runner_label":os.environ.get("RUNNER_OS"),"platform":platform.platform(),
       "processor":platform.processor(),"logical_cpus":psutil.cpu_count(),
       "reference_nps":1308308,"reference_cpu_model":"AMD EPYC 9V45 96-Core Processor",
       "cases":[],"started_utc":now()}
def save():
    state["heartbeat_utc"]=now()
    OUTPUT.write_text(json.dumps(state,indent=2),encoding="utf-8")
    if not TOKEN:return
    payload=base64.b64encode(json.dumps(state,separators=(",",":")).encode()).decode()
    for attempt in range(5):
        try:
            r=HTTP.get(API,timeout=25)
            sha=None if r.status_code==404 else r.raise_for_status() or r.json()["sha"]
            data={"message":f"Safrad host-only {MODE}: {len(state['cases'])} trials",
                  "content":payload,"branch":"main"}
            if sha:data["sha"]=sha
            z=HTTP.put(API,json=data,timeout=30)
            z.raise_for_status()
            return
        except Exception as error:
            print("CHECKPOINT_ERROR",repr(error),flush=True)
            time.sleep(attempt+1)
    raise RuntimeError("Failed to publish host-only benchmark checkpoint")
def command(args,limit=15):
    try:
        p=subprocess.run(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=limit,check=False)
        return {"code":p.returncode,"output":p.stdout.strip()[:1500]}
    except Exception as e:return {"error":repr(e)}
def engine_path():
    state["status"]="downloading_original_engine";save()
    ROOT.mkdir(parents=True,exist_ok=True)
    archive=ROOT/"original_safrad.zip"
    with requests.get(ENGINE_URL,stream=True,timeout=100) as response:
        response.raise_for_status()
        with archive.open("wb") as fp:
            for chunk in response.iter_content(65536):
                if chunk:fp.write(chunk)
    if not zipfile.is_zipfile(archive):raise RuntimeError("Official download invalid")
    with zipfile.ZipFile(archive) as fp:fp.extractall(ROOT)
    files=sorted(ROOT.rglob("*.exe"),key=lambda p:(0 if "safrad" in p.name.lower() else 1,len(p.name)))
    if not files:raise RuntimeError("No Safrad EXE")
    exe=files[0]
    real_hash=hashlib.sha256(exe.read_bytes()).hexdigest()
    if real_hash!=TARGET_HASH:raise RuntimeError("Original executable changed: "+real_hash)
    state["executable"]=str(exe)
    state["executable_hash_verified"]=True
    state["cpu_name"]=command(["powershell.exe","-NoProfile","-Command","(Get-CimInstance Win32_Processor).Name"]).get("output")
    state["power_active_initial"]=command(["powercfg","/getactivescheme"])
    save()
    return exe
def cases_for_mode():
    if MODE=="priority-affinity":
        return [
            ("baseline_A",45,"normal",None,False,False),
            ("affinity_cpu0",45,"normal",0,False,False),
            ("affinity_cpu1",45,"normal",1,False,False),
            ("affinity_cpu2",45,"normal",2,False,False),
            ("affinity_cpu3",45,"normal",3,False,False),
            ("baseline_B",45,"normal",None,False,False),
            ("priority_above_normal",45,"above",None,False,False),
            ("priority_high",45,"high",None,False,False),
            ("high_priority_cpu0",45,"high",0,False,False),
            ("baseline_C",45,"normal",None,False,False)
        ]
    if MODE=="power-timer":
        return [
            ("baseline_A",55,"normal",None,False,False),
            ("timer_1ms",55,"normal",None,True,False),
            ("high_performance_powerplan",55,"normal",None,False,True),
            ("high_power_and_timer",55,"normal",None,True,True),
            ("high_power_high_priority",55,"high",None,False,True),
            ("baseline_B",55,"normal",None,False,False),
        ]
    if MODE=="repeat-reference":
        return [("reference_same_runner_A",120,"normal",None,False,False),
                ("reference_same_runner_B",120,"normal",None,False,False)]
    raise ValueError("Invalid mode")
def bench(exe,name,seconds,priority,core,hires,highpower):
    original_power=command(["powercfg","/getactivescheme"])
    power_change=None
    timer_code=None
    if highpower:power_change=command(["powercfg","/setactive","SCHEME_MIN"])
    if hires:
        timer_code=ctypes.windll.winmm.timeBeginPeriod(1)
    p=None
    started=None
    try:
        p=subprocess.Popen([str(exe)],cwd=str(exe.parent),stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,
                            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        ps=psutil.Process(p.pid)
        readq=queue.Queue()
        def reader():
            while True:
                raw=p.stdout.readline()
                if not raw:break
                readq.put((time.monotonic(),raw.decode("utf-8","replace").strip()))
        threading.Thread(target=reader,daemon=True).start()
        def send(s):
            p.stdin.write((s+"\n").encode("ascii"));p.stdin.flush()
        def token(value):
            limit=time.monotonic()+25
            while time.monotonic()<limit:
                if p.poll() is not None:raise RuntimeError("Safrad exited during UCI")
                try:_,line=readq.get(timeout=.25)
                except queue.Empty:continue
                if line==value:return
            raise TimeoutError("No "+value)
        send("uci");token("uciok")
        send("isready");token("readyok")
        if priority=="above":ps.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
        elif priority=="high":ps.nice(psutil.HIGH_PRIORITY_CLASS)
        else:ps.nice(psutil.NORMAL_PRIORITY_CLASS)
        if core is not None:ps.cpu_affinity([core])
        assigned_affinity=ps.cpu_affinity()
        assigned_priority=ps.nice()
        send("ucinewgame")
        send("position fen "+FEN)
        cpu_start=ps.cpu_times()
        cpu_base=cpu_start.user+cpu_start.system
        started=time.monotonic()
        send("go infinite")
        last={"nodes":0,"nps":None,"time_ms":None,"depth":None}
        stopped=False
        bestmove=None
        while True:
            elapsed=time.monotonic()-started
            if elapsed>=seconds and not stopped:
                send("stop");stopped=True
            if stopped and elapsed>seconds+15:
                raise TimeoutError("No bestmove returned following stop")
            if p.poll() is not None:raise RuntimeError("Safrad exited during search")
            try:recorded,line=readq.get(timeout=.1)
            except queue.Empty:continue
            if line.startswith("info "):
                for key,regex in (("nodes",r"\bnodes\s+(\d+)"),
                                  ("nps",r"\bnps\s+(\d+)"),
                                  ("time_ms",r"\btime\s+(\d+)"),
                                  ("depth",r"\bdepth\s+(\d+)")):
                    match=re.search(regex,line)
                    if match:last[key]=int(match.group(1))
            elif line.startswith("bestmove"):
                bestmove=line.split()[1] if len(line.split())>1 else None
                break
        wall=time.monotonic()-started
        after=ps.cpu_times()
        cpu_seconds=(after.user+after.system)-cpu_base
        result={"case":name,"seconds_target":seconds,"seconds_wall":round(wall,3),
                "cpu_seconds":round(cpu_seconds,3),"cpu_utilization_fraction":round(cpu_seconds/wall,3),
                "priority_requested":priority,"priority_actual":assigned_priority,
                "affinity_requested":core,"affinity_actual":assigned_affinity,
                "timer_request_result":timer_code,"highpower_request":power_change,
                "active_power":command(["powercfg","/getactivescheme"]),
                "nodes":last["nodes"],"uci_nps":last["nps"],
                "nodes_per_wall_second":round(last["nodes"]/wall),
                "nodes_per_cpu_second":round(last["nodes"]/cpu_seconds) if cpu_seconds>0 else None,
                "reported_elapsed_ms":last["time_ms"],"depth":last["depth"],
                "bestmove":bestmove,"ended_utc":now()}
        if not bestmove:raise RuntimeError("No bestmove")
        return result
    finally:
        if p:
            try:
                if p.poll() is None:
                    p.stdin.write(b"quit\n");p.stdin.flush()
                p.wait(timeout=2)
            except Exception:
                try:p.kill();p.wait(timeout=2)
                except Exception:pass
        if hires:
            ctypes.windll.winmm.timeEndPeriod(1)
        if highpower:
            guid_match=re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",original_power.get("output",""),re.I)
            if guid_match:command(["powercfg","/setactive",guid_match.group(1)])
def main():
    exe=engine_path()
    state["status"]="running"
    save()
    for name,duration,priority,core,timer,power in cases_for_mode():
        if core is not None and core>=psutil.cpu_count():
            result={"case":name,"skipped":"CPU not exposed"}
        else:
            try:result=bench(exe,name,duration,priority,core,timer,power)
            except Exception as e:result={"case":name,"error":repr(e),"ended_utc":now()}
        state["cases"].append(result)
        print("HOST_CASE",json.dumps(result),flush=True)
        save()
    state["status"]="completed"
    state["ended_utc"]=now()
    save()
if __name__=="__main__":
    try:main()
    except Exception as error:
        state.update(status="fatal_error",error=repr(error),ended_utc=now())
        save()
        raise
