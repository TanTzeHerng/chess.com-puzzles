#!/usr/bin/env python3
import csv,glob,json,math,os,collections
from pathlib import Path
import numpy as np,matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

files=sorted(glob.glob("shard_artifacts/**/summary.csv",recursive=True))
if not files:raise RuntimeError("No sharded results found")
out=Path("combined_results");out.mkdir(exist_ok=True)
data={};duplicates=[]
for name in files:
    for r in csv.DictReader(open(name,newline="")):
        if r["id"] in data: duplicates.append(r["id"])
        data[r["id"]]=r
if duplicates:raise RuntimeError("Duplicate puzzle IDs: "+str(duplicates[:20]))
rows=list(data.values());rows.sort(key=lambda r:(int(r["rating"]),int(r["id"])))
expected=19492
good=[r for r in rows if r["sum_node_budgets"].strip()]
with (out/"all_puzzles.csv").open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
summary={"files":files,"expected_puzzles":expected,"attempted":len(rows),"qualifying":len(good),
         "censored":len(rows)-len(good),"missing":expected-len(rows),"lichess_win_chance_gap":0.7,"lichess_min_advantage_cp":200,"final_solver_move_exempt_from_uniqueness":True,
         "max_tested_budget":262144,"notes":"Original Stockfish 17.1 evaluated by Lichess generator v50 win-chances gap >0.7 on [-1,1] plus best score >=+200cp or winning mate; final solver move exempted from uniqueness per published Chess.com puzzle selection principles. Simplified multiple-mate-in-one handling. TT preserved across budgets and solver moves within puzzle; reset between puzzles. Tested budgets only, not exact asymptotic minimum. Censored cases excluded from smoothing."}
(out/"SUMMARY.json").write_text(json.dumps(summary,indent=2))
print("AGGREGATED_RESULTS",json.dumps(summary),flush=True)
if not good:raise SystemExit("No fully qualifying puzzles: no smoothing possible")
x=np.array([int(r["rating"]) for r in good],float)
n=np.array([int(r["sum_node_budgets"]) for r in good],float)
y=np.log10(n)
gx=np.arange(int(x.min()),int(x.max())+1,10,dtype=float)
bandwidth=150.0
curve=[];effective=[]
for xx in gx:
    weight=np.exp(-0.5*((x-xx)/bandwidth)**2)
    ess=(weight.sum()**2)/(weight@weight)
    effective.append(ess)
    curve.append(10**(weight@y/weight.sum()) if ess>=10 else float("nan"))
with (out/"smoothed_curve.csv").open("w",newline="") as f:
    w=csv.writer(f);w.writerow(["rating","smoothed_geometric_mean_summed_node_budget","effective_sample_size"])
    w.writerows(zip(gx,curve,effective))
fig,ax=plt.subplots(figsize=(11,6))
ax.scatter(x,n,s=8,alpha=.16,label=f"Puzzle totals (n={len(good)})")
ax.plot(gx,curve,lw=2.6,label="Gaussian smoothing (150 rating points, logarithmic nodes)")
ax.set_yscale("log")
ax.set_xlabel("Chess.com puzzle rating (September 16, 2026 snapshot)")
ax.set_ylabel("Sum of Lichess-gap qualifying per-move node budgets (logarithmic scale)")
ax.set_title("Original Stockfish 17.1, 2500+ Chess.com puzzles")
ax.grid(alpha=.2)
ax.legend(loc="best")
fig.tight_layout()
fig.savefig(out/"smoothed_rating_vs_nodes.png",dpi=190)
plt.close(fig)
print("FINAL_GRAPH",out/"smoothed_rating_vs_nodes.png",flush=True)
