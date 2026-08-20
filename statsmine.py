#!/usr/bin/env python3
"""Aggregate live-session stats from ninfer prod logs (aggregates only, no content)."""
import json,re,collections
ERR="/opt/ninfer/logs/prod.err"; JL="/opt/ninfer/logs/prod.jsonl"
try:
    tail=open(ERR,"rb").read()[-3000000:].decode("utf-8","replace")
    ts=[l for l in tail.splitlines() if "tok/s" in l or "throughput" in l.lower()]
    print("last stats lines (%d total):"%len(ts))
    for l in ts[-6:]: print("  "+l.strip()[:160])
    cac=[int(x) for x in re.findall(r"cache=(\d+)",tail)]
    hits=[c for c in cac if c>0]
    if cac: print("session requests so far: %d, reuse on %d (%.0f%%), tokens reused %s"%(len(cac),len(hits),100.0*len(hits)/max(1,len(cac)),format(sum(hits),",")))
except Exception as e: print("err log:",e)
try:
    recs=[]
    for line in open(JL):
        line=line.strip()
        if line:
            try: recs.append(json.loads(line))
            except Exception: pass
    done=[r for r in recs if r.get("event")=="request_done"]
    print("jsonl request_done:",len(done))
    if done:
        r0=done[-1]
        for k in ("speculative","timings_seconds","result"):
            v=r0.get(k)
            print("shape %s: %s"%(k, json.dumps(v)[:220] if not isinstance(v,dict) else "{"+", ".join("%s=%s"%(a,json.dumps(b)[:24]) for a,b in list(v.items())[:8])+"}"))
        acc=drf=0; gen=0; dec_t=0.0; pre_t=0.0; ptok=0
        for r in done:
            s=r.get("speculative") or {}
            for ka in ("accepted","accepted_tokens"):
                if ka in s: acc+=s[ka]
            for kd in ("drafted","draft_tokens","proposed"):
                if kd in s: drf+=s[kd]
            t=r.get("timings_seconds") or {}
            res=r.get("result") or {}
            gen+=res.get("completion_tokens",0) or 0
            ptok+=res.get("prompt_tokens",0) or 0
            for kd in ("decode","generation","decode_seconds"):
                if kd in t: dec_t+=t[kd]
            for kp in ("prefill","prefill_seconds"):
                if kp in t: pre_t+=t[kp]
        print("gen tokens=%d prompt tokens=%d"%(gen,ptok))
        if drf: print("spec acceptance: %.1f%% (%d/%d)"%(100.0*acc/drf,acc,drf))
        if dec_t>0 and gen: print("decode rate: %.1f tok/s over %.0fs decode time"%(gen/dec_t,dec_t))
        if pre_t>0 and ptok: print("prefill observed: %.0f tok/s over %.0fs"%(ptok/pre_t,pre_t))
except Exception as e: print("jsonl:",e)
print("STATSMINE_DONE")
