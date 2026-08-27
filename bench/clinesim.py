#!/usr/bin/env python3
"""Cline-shaped TTFT test: does turn N+1 start fast?
SEQ mode: one conversation grows turn by turn (normal Cline pattern).
INTERLEAVE mode: two independent conversations alternate (Cline task + FAST side ask).
Per turn: prompt tokens, TTFT (first streamed token), total wall."""
import json,os,time,urllib.request,urllib.error
D=os.path.dirname(os.path.abspath(__file__))
BASE=os.environ.get("TARGET_URL","http://127.0.0.1:8080")
MODEL=os.environ.get("TARGET_MODEL","qwen3.8-27b")
TURNS=int(os.environ.get("TURNS","8"))
CHUNK=int(os.environ.get("CHUNK_TOKENS","8000"))
MODE=os.environ.get("MODE","both")
EFFORT=os.environ.get("EFFORT","none")
try: KEY=open(os.path.join(D,"api-key.txt")).read().strip()
except Exception: KEY=""
H={"Content-Type":"application/json"}
if KEY: H["Authorization"]="Bearer "+KEY
LINE="def step_%05d(ctx):\n    return transform(ctx, key=%d)  # pipeline stage\n"
def chunk(tag,i):
    n=int(CHUNK/16.0)
    return "[%s chunk %d]\n"%(tag,i)+"".join(LINE%(j+i*10000,j%9) for j in range(n))+"\nAcknowledge receipt of chunk %d in one short sentence."%i
SYS="You are a precise coding assistant working inside an IDE extension. Keep answers short."
USE_SO=[True]
def turn(messages):
    body=dict(model=MODEL,max_tokens=int(os.environ.get("MAXTOK","120")),temperature=1.0,reasoning_effort=EFFORT,
              stream=True,messages=messages)
    if USE_SO[0]: body["stream_options"]={"include_usage":True}
    req=urllib.request.Request(BASE+"/v1/chat/completions",data=json.dumps(body).encode(),headers=H)
    t0=time.time(); ttft=None; text=""; ptok=None
    try:
        resp=urllib.request.urlopen(req,timeout=900)
    except urllib.error.HTTPError as e:
        if USE_SO[0]:
            USE_SO[0]=False
            return turn(messages)
        raise
    with resp as r:
        for raw in r:
            raw=raw.decode("utf-8","replace").strip()
            if not raw.startswith("data:"): continue
            payload=raw[5:].strip()
            if payload=="[DONE]": break
            try: j=json.loads(payload)
            except Exception: continue
            u=j.get("usage")
            if u and u.get("prompt_tokens"): ptok=u.get("prompt_tokens")
            ch=j.get("choices") or []
            if ch:
                d=ch[0].get("delta") or {}
                c=d.get("content") or d.get("reasoning_content") or ""
                if c and ttft is None: ttft=time.time()-t0
                if d.get("content"): text+=d["content"]
    return ttft,time.time()-t0,ptok,text
def report(rows,label):
    late=[r[-2] for r in rows[len(rows)//2:] if r[-2] is not None]
    if late: print("%s late-turn TTFT mean: %.2fs"%(label,sum(late)/len(late)),flush=True)
if MODE in ("both","seq"):
    print("== SEQ: one growing conversation, %d turns x ~%d tok chunks =="%(TURNS,CHUNK),flush=True)
    msgs=[{"role":"system","content":SYS}]; rows=[]
    for i in range(TURNS):
        msgs.append({"role":"user","content":chunk("A",i)})
        ttft,wall,ptok,text=turn(msgs)
        msgs.append({"role":"assistant","content":text or "ok"})
        rows.append((i,ptok,ttft,wall))
        print("  turn %d: prompt=%-7s ttft=%s wall=%5.2fs"%(i,ptok,("%5.2fs"%ttft) if ttft else "  n/a",wall),flush=True)
    report(rows,"SEQ")
if MODE in ("both","interleave"):
    print("== INTERLEAVE: two conversations alternating, %d turns total =="%TURNS,flush=True)
    convs={"A":[{"role":"system","content":SYS}],"B":[{"role":"system","content":SYS}]}
    rows=[]
    for i in range(TURNS):
        tag="A" if i%2==0 else "B"
        msgs=convs[tag]
        msgs.append({"role":"user","content":chunk(tag,i)})
        ttft,wall,ptok,text=turn(msgs)
        msgs.append({"role":"assistant","content":text or "ok"})
        rows.append((tag,i,ptok,ttft,wall))
        print("  conv %s turn %d: prompt=%-7s ttft=%s wall=%5.2fs"%(tag,i,ptok,("%5.2fs"%ttft) if ttft else "  n/a",wall),flush=True)
    report(rows,"INTERLEAVE")
print("CLINESIM_DONE")
