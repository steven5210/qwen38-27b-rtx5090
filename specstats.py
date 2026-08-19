#!/usr/bin/env python3
"""MTP speculative-decode acceptance, broken out per workload type."""
import json, os, re, time, urllib.request
D=os.path.dirname(os.path.abspath(__file__))
BASE="http://127.0.0.1:8000"; KEY=open(os.path.join(D,"api-key.txt")).read().strip()
def post(p,d,t=900):
    r=urllib.request.Request(BASE+p,data=json.dumps(d).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})
    return json.loads(urllib.request.urlopen(r,timeout=t).read().decode())
def raw_metrics():
    r=urllib.request.Request(BASE+"/metrics",headers={"Authorization":"Bearer "+KEY})
    return urllib.request.urlopen(r,timeout=30).read().decode()
def spec_counters():
    out={}
    for line in raw_metrics().splitlines():
        if line.startswith("#"): continue
        if not re.search(r"spec|accept|draft", line): continue
        m=re.match(r"^(\S+?)(\{[^}]*\})?\s+([0-9.eE+-]+)$", line)
        if m:
            key=m.group(1)+(re.sub(r'.*position="(\d+)".*', r'@pos\1', m.group(2)) if m.group(2) and 'position' in m.group(2) else "")
            out[key]=out.get(key,0.0)+float(m.group(3))
    return out

print("=== spec-decode metric names exposed by this build ===")
c0=spec_counters()
for k in sorted(c0): print("  %-58s %s" % (k, c0[k]))
print()

WORK=[
 ("short_codegen_nothink", dict(max_tokens=400, messages=[{"role":"user","content":
   "Write a Python function `chunk(lst, n)` that splits a list into n-sized chunks. Code only."}],
   chat_template_kwargs={"enable_thinking": False})),
 ("long_code_thinking", dict(max_tokens=3000, messages=[{"role":"user","content":
   "Implement an LRU cache with per-key TTL in Python: get/put/__len__, O(1) amortised, "
   "expired keys must not count toward capacity. Explain your design choices, then give the code."}],
   chat_template_kwargs={"reasoning_effort":"medium"})),
 ("deep_reasoning", dict(max_tokens=3000, messages=[{"role":"user","content":
   "A distributed queue must guarantee exactly-once delivery across a network partition where "
   "clocks drift up to 500ms. Reason carefully about whether that is achievable, and what the "
   "weakest assumption is that makes it achievable."}],
   chat_template_kwargs={"reasoning_effort":"xhigh"})),
 ("repeat_cached", None),  # rerun of #2 verbatim -> prefix cache hit
]
prev=spec_counters()
rows=[]
for name, body in WORK:
    if body is None:
        body=dict(WORK[1][1])
    payload=dict(model="qwen3.8-27b", temperature=1.0, top_p=0.95, **body)
    t0=time.time(); r=post("/v1/chat/completions", payload); dt=time.time()-t0
    u=r.get("usage",{}); cur=spec_counters()
    d={k: cur.get(k,0)-prev.get(k,0) for k in cur}
    prev=cur
    # Precise keys only. num_drafts is an EVENT count, not tokens -- summing it into
    # num_draft_tokens understates acceptance badly (72% vs the true 96%).
    acc      = d.get("vllm:spec_decode_num_accepted_tokens_total", 0.0)
    drafted  = d.get("vllm:spec_decode_num_draft_tokens_total", 0.0)
    n_drafts = d.get("vllm:spec_decode_num_drafts_total", 0.0)
    per_pos={k:v for k,v in d.items()
             if "@pos" in k and "accepted_tokens_per_pos_total" in k}
    rate=(100.0*acc/drafted) if drafted else None
    out_tok=u.get("completion_tokens")
    rows.append((name, out_tok, round(dt,1), round(out_tok/dt,1), acc, drafted, rate, per_pos))
    print("%-22s out=%-5s %6.1fs %6.1f tok/s  accepted=%-8.0f drafted=%-8.0f acceptance=%s"
          % (name, out_tok, dt, out_tok/dt, acc, drafted,
             ("%.1f%%" % rate) if rate is not None else "n/a"), flush=True)
    if per_pos and n_drafts:
        print("      per-position acceptance: " + "  ".join(
            "%s=%.1f%%" % (k.split("@")[-1], 100.0*v/n_drafts) for k,v in sorted(per_pos.items())))
        print("      drafts=%.0f  mean accepted per draft=%.2f of 3" % (n_drafts, acc/n_drafts))
c=spec_counters()
A=c.get("vllm:spec_decode_num_accepted_tokens_total",0.0)
T=c.get("vllm:spec_decode_num_draft_tokens_total",0.0)
N=c.get("vllm:spec_decode_num_drafts_total",0.0)
print("\n=== lifetime totals since boot ===")
print("  drafts=%.0f  draft_tokens=%.0f  accepted=%.0f  overall acceptance=%.1f%%"
      % (N, T, A, 100.0*A/T if T else 0))
print("  mean accepted per draft = %.2f of 3" % (A/N if N else 0))
for i in range(3):
    v=c.get("vllm:spec_decode_num_accepted_tokens_per_pos_total@pos%d"%i,0.0)
    print("  position %d accepted %.1f%% of drafts" % (i, 100.0*v/N if N else 0))
print("\nSPECSTATS_DONE")
