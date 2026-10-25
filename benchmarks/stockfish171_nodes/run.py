#!/usr/bin/env python3
import argparse,csv,json,zipfile,random,time,os
from pathlib import Path
import chess,chess.engine

TCN="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?{~}(^)[_]@#$"
def decode(t):
    moves=[]
    for i in range(0,len(t),2):
        a,b=TCN.index(t[i]),TCN.index(t[i+1]);promo=""
        if b>63:
            promo="qnrbk"[(b-64)//3]
            b=a+(-8 if a<16 else 8)+(b-64)%3-1
        moves.append("abcdefgh"[a%8]+str(a//8+1)+"abcdefgh"[b%8]+str(b//8+1)+promo)
    return moves
def get_input(p):
    if p.endswith(".zip"):
        with zipfile.ZipFile(p) as z:
            nm=next(i for i in z.namelist() if i.endswith("puzzles.json"))
            data=json.loads(z.read(nm))
    else:data=json.loads(Path(p).read_text())
    rows=data.values() if isinstance(data,dict) else data
    for x in rows:
        if int(x.get("rating",0))<2500:continue
        try:
            if "puzzleFen" in x and isinstance(x.get("solutionUci"),list):
                yield {"id":str(x["id"]),"rating":int(x["rating"]),"fen":x["puzzleFen"],"line":x["solutionUci"]}
                continue
            line=decode(x["tcnMoveList"])
            board=chess.Board(x["initialFen"])
            setup=chess.Move.from_uci(line[0])
            if setup not in board.legal_moves:continue
            board.push(setup);fen=board.fen()
            for u in line[1:]:
                m=chess.Move.from_uci(u)
                if m not in board.legal_moves:raise ValueError("bad source move")
                board.push(m)
            yield {"id":str(x["id"]),"rating":int(x["rating"]),"fen":fen,"line":line[1:]}
        except Exception as e:
            print("BAD_SOURCE",x.get("id"),repr(e),flush=True)

def verdict(eng,board,budget,game,expected):
    info=eng.analyse(board,chess.engine.Limit(nodes=budget),multipv=min(2,board.legal_moves.count()),game=game,
                     info=chess.engine.INFO_SCORE|chess.engine.INFO_PV|chess.engine.INFO_BASIC)
    if isinstance(info,dict):info=[info]
    lines=[]
    for x in info:
        score=x.get("score")
        val=score.pov(board.turn).score(mate_score=100000) if score else None
        pv=x.get("pv") or []
        lines.append({"move":pv[0].uci() if pv else None,"score":val,"nodes":x.get("nodes"),
                     "depth":x.get("depth"),"bound":bool(x.get("lowerbound") or x.get("upperbound"))})
    lines.sort(key=lambda x: x["score"] if x["score"] is not None else -10**9,reverse=True)
    ok=(bool(lines) and lines[0]["move"]==expected and
        lines[0]["score"] is not None and lines[0]["score"]>=100 and
        (board.legal_moves.count()==1 or (len(lines)>1 and
        lines[1]["score"] is not None and lines[1]["score"]<100)))
    return bool(ok),lines

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dataset",required=True);ap.add_argument("--engine",required=True)
    ap.add_argument("--output",default="results")
    ap.add_argument("--pilot",type=int,default=60)
    ap.add_argument("--budgets",default="512,1024,2048,4096,8192,16384,32768,65536,131072,262144")
    ap.add_argument("--confirm",type=int,default=3)
    ap.add_argument("--shard-count",type=int,default=1)
    ap.add_argument("--shard-index",type=int,default=0)
    ap.add_argument("--seconds",type=float,default=1500)
    a=ap.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    allrows=list(get_input(a.dataset))
    budgets=sorted(set(map(int,a.budgets.split(","))))
    if a.pilot:
        rng=random.Random(171)
        buckets={}
        for r in allrows:
            band=min((r["rating"]-2500)//150,9)
            buckets.setdefault(band,[]).append(r)
        for arr in buckets.values():rng.shuffle(arr)
        chosen=[]
        while len(chosen)<a.pilot and any(buckets.values()):
            for band in sorted(buckets):
                if buckets[band] and len(chosen)<a.pilot:chosen.append(buckets[band].pop())
        allrows=chosen
    else:allrows.sort(key=lambda r:(r["rating"],int(r["id"])))
    if a.shard_count>1:
        assert 0<=a.shard_index<a.shard_count
        allrows=[r for i,r in enumerate(allrows) if i%a.shard_count==a.shard_index]
    print("DATASET_COUNT",len(allrows),"BUDGETS",budgets,"SHARD",a.shard_index,"/",a.shard_count, "WIN_PROBABILITY_PROXY_CP",100,flush=True)
    results=[];started=time.monotonic()
    engine=chess.engine.SimpleEngine.popen_uci(a.engine,timeout=180)
    print("ENGINE_ID",engine.id,flush=True)
    if "17.1" not in engine.id.get("name",""):
        raise RuntimeError("This is NOT Stockfish 17.1")
    engine.configure({"Threads":1,"Hash":64,"UCI_LimitStrength":False})
    journal=out/"details.jsonl";seen=set()
    if journal.exists():
        for line in journal.read_text().splitlines():
            try:
                p=json.loads(line);results.append(p);seen.add(p["id"])
            except Exception:pass
    try:
        for idx,r in enumerate(allrows):
            if r["id"] in seen:continue
            brd=chess.Board(r["fen"]);positions=[]
            for j,u in enumerate(r["line"]):
                if j%2==0:positions.append((brd.copy(),u))
                brd.push_uci(u)
            if not positions:continue
            result={"id":r["id"],"rating":r["rating"],"fen":r["fen"],"moves":[],"total":None,"status":"unresolved"}
            for brd,u in positions:result["moves"].append({"uci":u,"results":{},"threshold":None})
            for b in budgets:
                key=f'{r["id"]}:{b}'
                for j,(brd,u) in enumerate(positions):
                    try:ok,lines=verdict(engine,brd,b,key,u)
                    except Exception as ex:
                        ok=None;lines=[];print("ENGINE_ERROR",r["id"],b,str(ex),flush=True)
                    result["moves"][j]["results"][str(b)]={"ok":ok,"lines":lines}
            for m in result["moves"]:
                vals=[m["results"][str(b)]["ok"] for b in budgets]
                for i,b in enumerate(budgets):
                    if len(budgets)-i-1>=a.confirm and all(v is True for v in vals[i:]):
                        m["threshold"]=b;break
            if all(m["threshold"] is not None for m in result["moves"]):
                result["status"]="stable_within_tested_range"
                result["total"]=sum(m["threshold"] for m in result["moves"])
            with journal.open("a") as f:
                f.write(json.dumps(result,separators=(",",":"))+"\n")
                f.flush();os.fsync(f.fileno())
            results.append(result)
            print("PUZZLE_RESULT",r["id"],"rating",r["rating"],
                "solver_moves",len(positions),"sum",result["total"],"status",result["status"],flush=True)
            if time.monotonic()-started>a.seconds:
                print("WALLTIME_BOUND",len(results),flush=True);break
    finally:engine.quit()
    cols=["id","rating","solver_moves","sum_node_budgets","per_move_thresholds","status"]
    with (out/"summary.csv").open("w",newline="") as f:
        w=csv.writer(f);w.writerow(cols)
        for r in results:
            w.writerow([r["id"],r["rating"],len(r["moves"]),r["total"],
                ";".join(str(m["threshold"] or "") for m in r["moves"]),r["status"]])
    print("RUN_SUMMARY",json.dumps({"completed":len(results),"stable":sum(r["total"] is not None for r in results),
       "censored":sum(r["total"] is None for r in results),"budgets":budgets}),flush=True)
    try:
        import numpy as np,matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        pairs=[(r["rating"],r["total"]) for r in results if r["total"]]
        if pairs:
            x=np.array([p[0] for p in pairs]);y=np.log10([p[1] for p in pairs])
            fig,ax=plt.subplots(figsize=(9,5.7))
            ax.scatter(x,10**y,s=16,alpha=.6,label=f"Complete thresholds (n={len(pairs)})")
            if len(pairs)>=5 and len(set(x))>=4:
                gx=np.linspace(x.min(),x.max(),200);gy=[]
                for g in gx:
                    w=np.exp(-.5*((x-g)/150)**2)
                    ess=w.sum()**2/sum(w*w)
                    gy.append(10**(w@y/w.sum()) if ess>=4 else float("nan"))
                ax.plot(gx,gy,lw=2,label="150-rating Gaussian smoothing of log10 totals")
            ax.set(xlabel="Chess.com puzzle rating (Sept 2026 snapshot)",
                ylabel="Sum of observed stable per-move node budgets")
            ax.set_yscale("log");ax.grid(alpha=.2);ax.legend()
            fig.tight_layout();fig.savefig(out/"smoothed_graph.png",dpi=180);plt.close(fig)
            print("GRAPH_SAVED",flush=True)
        else:print("NO_GRAPH_DATA_NO_COMPLETE_PUZZLES",flush=True)
    except Exception as ex:print("GRAPH_ERROR",repr(ex),flush=True)

if __name__=="__main__":main()
