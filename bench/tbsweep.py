#!/usr/bin/env python3
"""Can xhigh + a thinking_token_budget beat plain medium? Sweep the budget.

Includes two NEW problems harder than the standing eval (which medium already aces 24/24,
leaving no headroom to show any xhigh upside). Both suites were validated against reference
implementations first, so a failure can only be the model's.
"""
import os, json, time, importlib.util, urllib.request, urllib.error, collections
D="/mnt/c/Users/StevenPC/Downloads/qwen38"
KEY=open(os.path.join(D,"api-key.txt")).read().strip()
URL="http://127.0.0.1:8000/v1/chat/completions"
spec=importlib.util.spec_from_file_location("ce", os.path.join(D,"codeeval.py"))
ce=importlib.util.module_from_spec(spec); spec.loader.exec_module(ce)
BASE={p["name"]:p for p in ce.PROBLEMS}

SCHED_TESTS = '''
m, s = schedule([(1,3,[]),(2,2,[]),(3,1,[1,2])], 2)
assert s[1] == 0 and s[2] == 0, s
assert s[3] == 3, s
assert m == 4, m
m, s = schedule([(1,5,[]),(2,1,[]),(3,1,[]),(4,1,[])], 1)
assert s[1] == 0 and s[2] == 5 and s[3] == 6 and s[4] == 7, s
assert m == 8, m
m, s = schedule([], 3); assert m == 0 and s == {}
m, s = schedule([(1,4,[]),(2,4,[]),(3,4,[])], 3)
assert m == 4 and s == {1:0,2:0,3:0}, (m,s)
try:
    schedule([(1,1,[2]),(2,1,[1])], 2); raise SystemExit("should raise on cycle")
except ValueError: pass
'''
CF_TESTS = '''
assert cont_frac(0.5, 10) == (1, 2)
assert cont_frac(3.14159265358979, 10) == (22, 7)
assert cont_frac(3.14159265358979, 200) == (355, 113)
assert cont_frac(0.333333333333, 3) == (1, 3)
assert cont_frac(2.0, 5) == (2, 1)
assert cont_frac(-0.75, 8) == (-3, 4)
'''
HARD=[
 dict(name="schedule", tests=SCHED_TESTS, prompt=(
  "Write a Python function `schedule(tasks, workers)`.\n"
  "`tasks` is a list of (id, duration, deps) where deps is a list of task ids that must "
  "COMPLETE before this task may start. `workers` is the number of tasks that can run in "
  "parallel. Simulate greedy list scheduling: at any moment, among the tasks whose deps are "
  "all complete, start the one with the LONGEST duration; break ties by SMALLEST id. A task "
  "occupies one worker for its whole duration. Return a tuple (makespan, starts) where "
  "makespan is the time the last task finishes and starts maps task id -> start time. "
  "Empty input returns (0, {}). Raise ValueError if the dependencies are cyclic. "
  "Output ONLY a python code block.")),
 dict(name="cont_frac", tests=CF_TESTS, prompt=(
  "Write a Python function `cont_frac(x, max_den)` returning the best rational approximation "
  "to the float `x` whose denominator is at most `max_den`, as a tuple (numerator, "
  "denominator) in lowest terms. 'Best' means minimising |x - n/d|. Handle negative x (the "
  "sign belongs to the numerator, denominator stays positive) and exact values. On an exact "
  "tie prefer the smaller denominator. Output ONLY a python code block.")),
]
PROBS=[BASE["lru_ttl"], BASE["wildcard_match"]]+HARD

def call(prompt, effort, budget, max_tokens=16384, seed=0):
    body=dict(model="qwen3.8-27b", max_tokens=max_tokens, temperature=1.0, top_p=0.95,
              reasoning_effort=effort, seed=seed,
              messages=[{"role":"user","content":prompt}])
    if budget: body["thinking_token_budget"]=budget
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})
    t0=time.time()
    try:
        r=json.load(urllib.request.urlopen(req,timeout=900)); ch=r["choices"][0]
        return dict(ok=True, secs=round(time.time()-t0,1), finish=ch.get("finish_reason"),
                    content=ch["message"].get("content") or "",
                    tokens=r["usage"]["completion_tokens"])
    except urllib.error.HTTPError as e:
        return dict(ok=False, err=" ".join(e.read().decode().split())[:120], secs=0)

ARMS=[("medium (control)","medium",None),
      ("xhigh budget 2500","xhigh",2500),
      ("xhigh budget 4000","xhigh",4000),
      ("xhigh budget 6000","xhigh",6000),
      ("xhigh budget 8000","xhigh",8000),
      ("xhigh NO budget","xhigh",None)]
SAMPLES=2
summary={}
for label,effort,budget in ARMS:
    print("\n===== %s =====" % label, flush=True)
    npass=n=0; secs=0.0; fin=collections.Counter()
    for p in PROBS:
        for i in range(SAMPLES):
            r=call(p["prompt"], effort, budget, seed=500+i)
            if not r["ok"]:
                print("  %-15s s%d ERROR %s" % (p["name"],i,r["err"])); n+=1; continue
            good,err=ce.run_tests(ce.extract_code(r["content"]), p["tests"])
            n+=1; npass+=1 if good else 0; secs+=r["secs"]; fin[r["finish"]]+=1
            print("  %-15s s%d %-4s finish=%-7s tok=%-6d %5.0fs %s"
                  % (p["name"],i,"OK" if good else "FAIL",r["finish"],r["tokens"],r["secs"],
                     "" if good else err.strip().replace("\n"," ")[:40]), flush=True)
    summary[label]=(npass,n,round(secs),dict(fin))
    print("  --> %d/%d in %ds  finish:%s" % (npass,n,round(secs),dict(fin)), flush=True)

print("\n" + "="*74)
print("%-22s %-9s %-9s %s" % ("arm","score","wall","finish reasons"))
print("-"*74)
for k,(a,b,s,f) in summary.items():
    print("%-22s %-9s %-9s %s" % (k, "%d/%d"%(a,b), "%ds"%s, f))
print("="*74)
best=max(summary.items(), key=lambda kv:(kv[1][0], -kv[1][2]))
print("best score (ties -> faster): %s" % best[0])
print("TBSWEEP_DONE")
