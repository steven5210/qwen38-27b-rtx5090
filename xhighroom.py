#!/usr/bin/env python3
"""How much output budget does xhigh ACTUALLY need to finish?

Every previous xhigh test capped it (6000, then 16384) and it hit the ceiling. This gives it
genuine room (48000) with a realistic coding-sized prompt, and records where it naturally
STOPS. That number decides whether raising Cline's Max Output makes xhigh viable.
"""
import os, json, time, importlib.util, urllib.request, urllib.error, statistics
D="/mnt/c/Users/StevenPC/Downloads/qwen38"
KEY=open(os.path.join(D,"api-key.txt")).read().strip()
URL="http://127.0.0.1:8000/v1/chat/completions"
spec=importlib.util.spec_from_file_location("ce", os.path.join(D,"codeeval.py"))
ce=importlib.util.module_from_spec(spec); spec.loader.exec_module(ce)
P={p["name"]:p for p in ce.PROBLEMS}

# realistic coding context: ~18K tokens of surrounding repo, like a Cline turn
FILLER=("\n\n## repo context (for realism -- the task is stated at the end)\n" +
        "".join("""
class Service%03d:
    def __init__(self, bus, store): self.bus=bus; self.store=store
    def handle(self, ev):
        rec = self.store.get(ev.key)
        if rec is None: return self.bus.emit("miss", ev.key)
        return self.bus.emit("hit", {"key": ev.key, "v": rec, "seq": ev.seq+%d})
""" % (i,i) for i in range(220)))

def call(prompt, max_tokens, effort, seed):
    body=dict(model="qwen3.8-27b", max_tokens=max_tokens, temperature=1.0, top_p=0.95,
              reasoning_effort=effort, seed=seed,
              messages=[{"role":"user","content":prompt}])
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})
    t0=time.time()
    try:
        r=json.load(urllib.request.urlopen(req,timeout=1800)); ch=r["choices"][0]
        return dict(ok=True, secs=round(time.time()-t0), finish=ch.get("finish_reason"),
                    content=ch["message"].get("content") or "",
                    ptok=r["usage"]["prompt_tokens"], tokens=r["usage"]["completion_tokens"])
    except urllib.error.HTTPError as e:
        return dict(ok=False, err=" ".join(e.read().decode().split())[:150])

# Efficiency: ONE high ceiling (48,000) and read the natural stopping point, rather than a
# retry ladder. 2 samples on lru_ttl (the marginal coin-flip case, where variance is the
# whole question) and 1 each on the rest for breadth. 5 requests, 4 problems.
NAMES=["lru_ttl","lru_ttl","wildcard_match","schedule_x","cont_frac_x"]
BUDGET=48000
print("xhigh with a REALISTIC ~18K coding prompt and 48,000 output tokens of room.")
print("Question: where does it naturally stop?\n")
SCHED_TESTS=open("/mnt/c/Users/StevenPC/Downloads/qwen38/hard_sched_tests.txt").read()
CF_TESTS=open("/mnt/c/Users/StevenPC/Downloads/qwen38/hard_cf_tests.txt").read()
P["schedule_x"]=dict(name="schedule_x", tests=SCHED_TESTS, prompt=(
  "Write a Python function `schedule(tasks, workers)`.\n"
  "`tasks` is a list of (id, duration, deps) where deps must COMPLETE before this task starts. "
  "`workers` is how many run in parallel. Greedy list scheduling: among tasks whose deps are "
  "complete, start the LONGEST duration first; ties by SMALLEST id. Return (makespan, starts) "
  "where starts maps id -> start time. Empty input returns (0, {}). Raise ValueError on cyclic "
  "deps. Output ONLY a python code block."))
P["cont_frac_x"]=dict(name="cont_frac_x", tests=CF_TESTS, prompt=(
  "Write a Python function `cont_frac(x, max_den)` returning the best rational approximation to "
  "float `x` with denominator <= max_den, as (numerator, denominator) in lowest terms. "
  "'Best' minimises |x - n/d|. Handle negative x (sign on the numerator, denominator positive) "
  "and exact values. On an exact tie prefer the smaller denominator. "
  "Output ONLY a python code block."))
stops=[]; npass=0; n=0
for idx, name in enumerate(NAMES):
    p=P[name]
    prompt=FILLER+"\n\n---\n\n"+p["prompt"]
    for i in [idx]:
        r=call(prompt, BUDGET, "xhigh", 300+i)
        if not r["ok"]: print("  %-15s s%d ERROR %s" % (name,i,r["err"])); continue
        good,err=ce.run_tests(ce.extract_code(r["content"]), p["tests"])
        n+=1; npass+=1 if good else 0
        if r["finish"]=="stop": stops.append(r["tokens"])
        print("  %-15s s%d %-4s finish=%-7s prompt=%-6d out=%-6d %4ds  %s"
              % (name,i,"OK" if good else "FAIL",r["finish"],r["ptok"],r["tokens"],r["secs"],
                 "" if good else err.strip().replace("\n"," ")[:40]), flush=True)
print("\n  score with real room: %d/%d" % (npass,n))
if stops:
    print("  natural stopping point (tokens): min=%d median=%d max=%d"
          % (min(stops), int(statistics.median(stops)), max(stops)))
    print("  -> a Max Output of %d would have fit every completed run" % (max(stops)+1000))
else:
    print("  nothing completed even at 48,000 tokens")
print("XHIGHROOM_DONE")
