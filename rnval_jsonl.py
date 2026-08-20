#!/usr/bin/env python3
import json
recs=[]
for line in open("/opt/ninfer/logs/rnval.jsonl"):
    line=line.strip()
    if not line: continue
    try:
        r=json.loads(line)
        if r.get("event")=="request_done": recs.append(r)
    except Exception: pass
print("requests: %d"%len(recs))
paths={}
print("ord  prompt  reused   path                 ttft_s")
for i,r in enumerate(recs):
    res=r.get("result") or {}; t=r.get("timings_seconds") or {}
    p=res.get("prefix_reuse_path","?"); paths[p]=paths.get(p,0)+1
    print("%3d %7d %7d  %-20s %6.2f"%(i,res.get("prompt_tokens",0),res.get("prefix_cache_hit_tokens",0),p,t.get("ttft",0)))
print("path totals:",json.dumps(paths))
