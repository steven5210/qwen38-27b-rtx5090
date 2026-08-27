#!/usr/bin/env python3
"""Endurance loop vs :8080 -- the test that exposed vLLM's original 27x collapse.
Cycles 1K/8K/20K/40K/60K contexts for DURATION_MIN, watching wall time and VRAM."""
import json,os,time,subprocess,urllib.request
D=os.path.dirname(os.path.abspath(__file__))
URL=os.environ.get("TARGET_URL","http://127.0.0.1:8080/v1/chat/completions")
try: KEY=open(os.path.join(D,"api-key.txt")).read().strip()
except Exception: KEY=""
H={"Content-Type":"application/json"}
if KEY: H["Authorization"]="Bearer "+KEY
DUR=float(os.environ.get("DURATION_MIN","22"))*60
LINE="def f_%05d(x):\n    return x * %d  # filler with text to tokenize\n"
def prompt_of(tokens):
    n=int(tokens/16.5)
    return "".join(LINE%(i,i%9) for i in range(n))+"\nSummarize what this module does in two sentences."
def vram():
    try:
        o=subprocess.run(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"],
                         capture_output=True,text=True,timeout=5)
        return int(o.stdout.strip())
    except Exception: return -1
SIZES=[int(x) for x in os.environ.get("CTX_SIZES","1000,8000,20000,40000,60000").split(",")]
pre={s:prompt_of(s) for s in SIZES}
t0=time.time(); rows=[]; i=0; errors=0
while time.time()-t0 < DUR:
    s=SIZES[i%len(SIZES)]; i+=1
    # unique head defeats prefix reuse so every request does real prefill work
    body=dict(model="qwen3.8-27b",max_tokens=200,temperature=1.0,reasoning_effort="medium",
              messages=[{"role":"user","content":"[iter %d]\n"%i+pre[s]}])
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers=H)
    rt0=time.time()
    try:
        r=json.load(urllib.request.urlopen(req,timeout=600))
        dt=time.time()-rt0; u=r["usage"]; v=vram()
        rows.append((time.time()-t0,s,dt,u["completion_tokens"],v))
        print("t=%5.1fmin ctx=%6d wall=%6.1fs out=%3d vram=%d"%((time.time()-t0)/60,s,dt,u["completion_tokens"],v),flush=True)
    except Exception as e:
        errors+=1
        print("t=%5.1fmin ctx=%6d ERROR %s"%((time.time()-t0)/60,s,str(e)[:90]),flush=True)
half=len(rows)//2
if half>1:
    def mean(xs): return sum(xs)/len(xs)
    w1=mean([r[2] for r in rows[:half]]); w2=mean([r[2] for r in rows[half:]])
    v=[r[4] for r in rows if r[4]>0]
    print("requests=%d errors=%d"%(len(rows),errors))
    print("wall first-half mean=%.1fs  second-half=%.1fs  (ratio %.2f -- flat is ~1.0)"%(w1,w2,w2/w1))
    print("vram min=%d max=%d drift=%d MiB"%(min(v),max(v),max(v)-min(v)))
print("ENDURE_DONE")
