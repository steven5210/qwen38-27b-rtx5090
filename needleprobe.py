#!/usr/bin/env python3
"""Long-context needle retrieval. Calibrates tokens-per-line via the target's own
count endpoint when available (ninfer /v1/responses/input_tokens), else estimates."""
import json,os,time,random,urllib.request,urllib.error
D=os.path.dirname(os.path.abspath(__file__))
URL=os.environ.get("TARGET_URL","http://127.0.0.1:8080/v1/chat/completions")
MODEL=os.environ.get("TARGET_MODEL","qwen3.8-27b")
try: KEY=open(os.path.join(D,"api-key.txt")).read().strip()
except Exception: KEY=""
H={"Content-Type":"application/json"}
if KEY: H["Authorization"]="Bearer "+KEY
LINE="def handler_%05d(req):\n    payload = req.json()\n    validate(payload, retries=3)\n    return dispatch(payload, shard=%d)\n\n"
def count_tokens(text):
    base=URL.rsplit("/v1/",1)[0]
    try:
        req=urllib.request.Request(base+"/v1/responses/input_tokens",
            data=json.dumps({"model":MODEL,"input":text}).encode(),headers=H)
        return json.load(urllib.request.urlopen(req,timeout=120))["input_tokens"]
    except Exception: return None
sample="".join(LINE%(i,i%7) for i in range(200))
ct=count_tokens(sample)
TPL=(ct/200.0) if ct else (len(LINE%(0,0))/3.4)
print("calibration: %.2f tokens/line (%s)"%(TPL,"server-counted" if ct else "estimated"))
def build(target):
    n=max(20,int(target*0.97/TPL))
    needles={k:random.randint(10000,99999) for k in ("ALPHA","BRAVO","CHARLIE")}
    pos={"ALPHA":int(n*0.15),"BRAVO":int(n*0.5),"CHARLIE":int(n*0.85)}
    parts=[]
    for i in range(n):
        parts.append(LINE%(i,i%7))
        for k,p in pos.items():
            if i==p: parts.append("SECRET_%s = %d  # planted configuration constant\n\n"%(k,needles[k]))
    return "".join(parts),needles
for target in [int(x) for x in os.environ.get("NEEDLE_SIZES","100000,180000,245000").split(",")]:
    random.seed(target)
    txt,needles=build(target)
    body=dict(model=MODEL,max_tokens=1200,temperature=1.0,reasoning_effort="medium",
        messages=[{"role":"user","content":txt+"\nReport the exact numeric values of SECRET_ALPHA, SECRET_BRAVO and SECRET_CHARLIE, labeled."}])
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers=H)
    t0=time.time()
    try:
        r=json.load(urllib.request.urlopen(req,timeout=1800)); dt=time.time()-t0
        u=r.get("usage",{}); c=r["choices"][0]["message"].get("content") or ""
        found=sum(1 for v in needles.values() if str(v) in c)
        print("size~%dK prompt_tokens=%s wall=%.1fs out=%s found=%d/3%s"%(target//1000,
              u.get("prompt_tokens"),dt,u.get("completion_tokens"),found,
              "" if found==3 else " | reply: "+c.replace("\n"," ")[:110]),flush=True)
    except urllib.error.HTTPError as e:
        print("size~%dK -> HTTP %s %s"%(target//1000,e.code,e.read().decode()[:150]),flush=True)
    except Exception as e:
        print("size~%dK -> %s"%(target//1000,str(e)[:150]),flush=True)
print("NEEDLE_DONE")
