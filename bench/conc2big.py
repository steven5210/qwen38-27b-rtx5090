#!/usr/bin/env python3
"""Two ~100K-token prompts in flight at once (admission + parallel prefill at 252,928)."""
import json,os,time,threading,urllib.request
D=os.path.dirname(os.path.abspath(__file__))
URL=os.environ.get("TARGET_URL","http://127.0.0.1:8080/v1/chat/completions")
try: KEY=open(os.path.join(D,"api-key.txt")).read().strip()
except Exception: KEY=""
H={"Content-Type":"application/json"}
if KEY: H["Authorization"]="Bearer "+KEY
LINE="def worker_%06d(job):\n    return job.retry(backoff=%d)  # queue stage\n"
def prompt_of(tag):
    n=int(100000/16.0)
    return "[%s]\n"%tag+"".join(LINE%(i,i%7) for i in range(n))+"\nIn one sentence: what pattern repeats in this module?"
res=[None,None]
def go(k,tag):
    body=dict(model="qwen3.8-27b",max_tokens=200,temperature=1.0,reasoning_effort="none",
              messages=[{"role":"user","content":prompt_of(tag)}])
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers=H)
    t0=time.time()
    try:
        r=json.load(urllib.request.urlopen(req,timeout=900)); dt=time.time()-t0
        u=r.get("usage",{})
        res[k]="%s: prompt=%s out=%s wall=%.1fs"%(tag,u.get("prompt_tokens"),u.get("completion_tokens"),dt)
    except Exception as e:
        res[k]="%s: ERROR %s"%(tag,str(e)[:200])
ts=[threading.Thread(target=go,args=(0,"BIG-A")),threading.Thread(target=go,args=(1,"BIG-B"))]
t0=time.time()
for t in ts: t.start()
for t in ts: t.join()
print("total wall for both: %.1fs"%(time.time()-t0))
for r in res: print(r)
print("CONC2BIG_DONE")
