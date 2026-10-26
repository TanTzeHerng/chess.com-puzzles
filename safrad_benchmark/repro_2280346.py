"""Isolated Safrad 2.1 mate-in-one false positive reproduction.

Original Safrad binary + Wine on GitHub Actions; NEVER run on the user's PC.
Fresh-process, repeated-search, and warm-previous-positions modes.
"""
import datetime as dt
import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import chess
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "forensics" / "repro_2280346.json"
ENGINE_URL = "https://sx.rosada.cz/projects/safrad-2.1/zip"
EXPECTED_SHA = "205556a25d8f201c642102e026c4dc778204b51aa29292ebd623faf9bd2d8d74"
REPO = os.environ.get("GITHUB_REPOSITORY", "TanTzeHerng/chess.com-puzzles")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
TARGET = "7r/3n1ppp/3Qpk2/4qb2/8/3B4/P5PP/5R1K w - - 5 33"
PRIOR = [
    "7r/3nkppp/Q2pp1b1/8/4q3/8/P3B1PP/3R3K w - - 2 30",
    "7r/3n1ppp/3Qpkb1/8/4q3/8/P3B1PP/3R3K w - - 1 31",
    "7r/3n1ppp/3Qpk2/5b2/4q3/8/P3B1PP/5R1K w - - 3 32",
]
def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def info_line(s):
    data={"raw":s}
    for k,p in {
       "depth":r"\bdepth\s+(\d+)", "nodes":r"\bnodes\s+(\d+)",
       "nps":r"\bnps\s+(\d+)", "elapsed_ms":r"\btime\s+(\d+)",
       "score_cp":r"\bscore\s+cp\s+(-?\d+)",
       "score_mate":r"\bscore\s+mate\s+(-?\d+)",
       "pv":r"\bpv\s+(.+)",
    }.items():
        m=re.search(p,s)
        if m:
            data[k]=m.group(1)
    return data

class Engine:
    def __init__(self, path):
        self.path=path
        self.proc=subprocess.Popen(["wine",str(path)],cwd=str(path.parent),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,bufsize=0)
        self.q=queue.Queue()
        self.reader=threading.Thread(target=self.read,daemon=True)
        self.reader.start()
        self.send("uci")
        self.wait_for("uciok",25)
        self.send("isready")
        self.wait_for("readyok",20)
    def read(self):
        while True:
            line=self.proc.stdout.readline()
            if not line:
                break
            self.q.put((time.monotonic(),line.decode("utf-8","replace").strip()))
    def send(self,msg):
        if self.proc.poll() is not None:
            raise RuntimeError("Safrad exited: "+str(self.proc.returncode))
        self.proc.stdin.write((msg+"\n").encode("ascii"))
        self.proc.stdin.flush()
    def wait_for(self,name,secs):
        deadline=time.monotonic()+secs
        while time.monotonic()<deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("Safrad died waiting for "+name)
            try:
                _,line=self.q.get(timeout=.15)
            except queue.Empty:
                continue
            if line.strip()==name:
                return
        raise TimeoutError(name+" not received")
    def search(self,fen,seconds):
        # Exact original protocol sequence:
        # ucinewgame; position fen FEN; go infinite.
        while not self.q.empty():
            try:self.q.get_nowait()
            except queue.Empty:break
        self.send("ucinewgame")
        self.send("position fen "+fen)
        self.send("go infinite")
        beginning=time.monotonic()
        stop_time=beginning+seconds
        grace=stop_time+8
        sent_stop=False
        events=[]
        all_info=[]
        bestmove=None
        while time.monotonic()<grace:
            if self.proc.poll() is not None:
                raise RuntimeError("Safrad died during search")
            if not sent_stop and time.monotonic()>=stop_time:
                self.send("stop")
                sent_stop=True
            try:
                when,raw=self.q.get(timeout=.04)
            except queue.Empty:
                continue
            if raw.startswith("info "):
                all_info.append(info_line(raw))
                events.append(raw)
            elif raw.startswith("bestmove"):
                bestmove=raw.split()[1] if len(raw.split())>1 else ""
                events.append(raw)
                break
            elif raw.startswith("read_error"):
                events.append(raw)
        if bestmove is None:
            raise TimeoutError("No bestmove after go infinite and stop")
        b=chess.Board(fen)
        try:
            legal=chess.Move.from_uci(bestmove.lower()) in b.legal_moves
        except (ValueError,AssertionError):
            legal=False
        if legal:
            move=chess.Move.from_uci(bestmove.lower())
            san=b.san(move)
            b.push(move)
            checkmate=b.is_checkmate()
            checking=b.is_check()
            replies=b.legal_moves.count()
        else:
            san=None
            checkmate=None
            checking=None
            replies=None
        mate=[x for x in all_info if "score_mate" in x]
        return {
            "bestmove":bestmove,"legal_move":legal,"san":san,
            "search_wall_seconds":round(time.monotonic()-beginning,5),
            "early_bestmove_without_stop":not sent_stop,
            "reported_mate_scores":mate[-6:],
            "last_info":all_info[-1] if all_info else None,
            "last_uci_lines":events[-20:],
            "uci_info_count":len(all_info),
            "move_is_check":checking,"move_is_checkmate":checkmate,
            "legal_replies_after":replies,
            "false_mate1_d6c6":(
                bestmove.lower()=="d6c6" and not checkmate
                and any(x.get("score_mate")=="1" for x in mate)),
        }
    def close(self):
        try:self.send("quit")
        except Exception:pass
        try:self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=3)

def fetch_engine():
    work=ROOT / "forensics" / "safrad_repro_engine"
    work.mkdir(parents=True,exist_ok=True)
    zip_path=work/"original.zip"
    if not zip_path.exists():
        with requests.get(ENGINE_URL,stream=True,timeout=(25,180),
                          headers={"User-Agent":"Mozilla/5.0"}) as r:
            r.raise_for_status()
            with zip_path.open("wb") as f:
                for c in r.iter_content(1024*1024):
                    if c:f.write(c)
    with zipfile.ZipFile(zip_path) as z:
        exes=[x for x in z.infolist() if x.filename.lower().endswith(".exe")
              and not any(p==".." for p in Path(x.filename).parts)]
        exes.sort(key=lambda x:(0 if "safrad" in x.filename.lower() else 1,len(x.filename)))
        if not exes:
            raise RuntimeError("No EXE in Safrad release")
        exe=work/Path(exes[0].filename).name
        exe.write_bytes(z.read(exes[0]))
    sha=hashlib.sha256(exe.read_bytes()).hexdigest()
    if sha != EXPECTED_SHA:
        raise RuntimeError("Safrad executable checksum mismatch: "+sha)
    return exe,sha

def upload(report):
    if not TOKEN:
        return
    api="https://api.github.com/repos/"+REPO+"/contents/safrad_benchmark/forensics/repro_2280346.json"
    import base64
    session=requests.Session()
    session.headers.update({"Authorization":"Bearer "+TOKEN,
         "Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"})
    for trial in range(6):
        head=session.get(api,timeout=20)
        if head.status_code not in (200,404):
            head.raise_for_status()
        body={"branch":"main","message":"Record independent Safrad 2280346 reproduction findings",
              "content":base64.b64encode(json.dumps(report,indent=2).encode()).decode()}
        if head.status_code==200:
            body["sha"]=head.json()["sha"]
        x=session.put(api,json=body,timeout=30)
        if x.status_code in (200,201):
            return
        if x.status_code not in (409,422):
            x.raise_for_status()
        time.sleep(.5+trial)
    raise RuntimeError("Could not upload standalone report")

def save(report):
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2),encoding="utf-8")
    upload(report)

def main():
    report={"puzzle_id":2280346,"engine":"Safrad 2.1.35.210",
         "engine_sha256_expected":EXPECTED_SHA,"test_position_fen":TARGET,
         "reference_bestmove":"f1f5","observed_in_benchmark":"d6c6",
         "benchmark_observed_nodes":18,"benchmark_observed_mate":1,
         "runner_id":os.environ.get("GITHUB_RUN_ID"),"started_utc":utc(),
         "tests":[]}
    board=chess.Board(TARGET)
    assert board.is_valid(), "Target FEN invalid"
    assert chess.Move.from_uci("d6c6") in board.legal_moves
    assert chess.Move.from_uci("f1f5") in board.legal_moves
    board.push_uci("d6c6")
    report["independent_legality_check"]={
        "after_d6c6_check":board.is_check(),
        "after_d6c6_checkmate":board.is_checkmate(),
        "legal_replies":board.legal_moves.count(),
        "after_d6c6_fen":board.fen()}
    assert not board.is_checkmate() and board.legal_moves.count()>0
    save(report)
    exe,sha=fetch_engine()
    report["verified_engine_sha256"]=sha
    save(report)
    def add(test_name,number,run):
        t={"mode":test_name,"trial":number,"started_utc":utc()}
        try:t.update(run())
        except Exception as exc:
            t["error"]=repr(exc)
        report["tests"].append(t)
        report["summary"]={
            "completed_trials":len(report["tests"]),
            "reproduced_false_mate1":sum(x.get("false_mate1_d6c6",False) for x in report["tests"]),
            "d6c6_bestmove":sum(x.get("bestmove","").lower()=="d6c6" for x in report["tests"]),
            "correct_f1f5":sum(x.get("bestmove","").lower()=="f1f5" for x in report["tests"]),
            "crashes_or_timeouts":sum("error" in x for x in report["tests"]),
        }
        print("REPRO_TRIAL",json.dumps(t),flush=True)
        save(report)
    def fresh():
        e=Engine(exe)
        try:return e.search(TARGET,3.0)
        finally:e.close()
    # 12 completely clean Safrad launches, short searches.
    for i in range(12):
        add("fresh_process_3s",i+1,fresh)
    # 8 positions on a reused engine process; ucinewgame every time.
    e=Engine(exe)
    try:
        for i in range(8):
            add("same_process_3s",i+1,lambda:e.search(TARGET,3.0))
    finally:e.close()
    # Test impact of the earlier three consecutive solver positions.
    for i in range(4):
        def warm():
            e=Engine(exe)
            try:
                warmups=[e.search(f,1.0) for f in PRIOR]
                result=e.search(TARGET,3.0)
                result["preceding_positions"]=[{"fen":f,"bestmove":x["bestmove"]}
                    for f,x in zip(PRIOR,warmups)]
                return result
            finally:e.close()
        add("prewarmed_prior_solver_positions_3s",i+1,warm)
    report["finished_utc"]=utc()
    report["completed"]=True
    save(report)
    print("FINAL_SUMMARY",json.dumps(report["summary"]),flush=True)

if __name__=="__main__":
    main()
