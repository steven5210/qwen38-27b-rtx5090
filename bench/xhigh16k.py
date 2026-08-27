#!/usr/bin/env python3
"""Do the truncated problems pass at xhigh when given Cline's real 16,384-token budget?"""
import os, sys, json, importlib.util, time
D="/mnt/c/Users/StevenPC/Downloads/qwen38"
os.environ["EVAL_EFFORT"]="xhigh"
spec=importlib.util.spec_from_file_location("ce", os.path.join(D,"codeeval.py"))
ce=importlib.util.module_from_spec(spec); spec.loader.exec_module(ce)

TARGETS=["version_compare","toposort","apply_patch","lru_ttl","json_path","wildcard_match"]
probs={p["name"]: p for p in ce.PROBLEMS} if hasattr(ce,"PROBLEMS") else None
if probs is None:
    print("could not find PROBLEMS list; attrs:", [a for a in dir(ce) if a.isupper()][:20]); sys.exit(1)

BUDGET=int(os.environ.get("BUDGET","16384"))
print("effort=xhigh  max_tokens=%d  (eval default was 6000)\n" % BUDGET)
tot=p_ok=0
for name in TARGETS:
    if name not in probs: print("!! %s not found" % name); continue
    pr=probs[name]
    for i in range(2):
        r=ce.chat([{"role":"user","content":pr["prompt"]}], max_tokens=BUDGET, seed=1000+i)
        ok,err=ce.run_tests(ce.extract_code(r["content"]), pr["tests"])
        tot+=1; p_ok+=1 if ok else 0
        print("%-16s s%d  %-4s finish=%-7s tokens=%-6d %5.0fs  %s"
              % (name,i,"OK" if ok else "FAIL", r["finish"], r["tokens"], r["secs"],
                 "" if ok else err.strip().replace("\n"," ")[:60]), flush=True)
print("\nxhigh @ %d tokens: %d/%d passed" % (BUDGET,p_ok,tot))
print("(same problems at xhigh @ 6000 scored 3/18; at medium @ 6000 they were 18/18)")
print("XHIGH16K_DONE")
