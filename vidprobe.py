#!/usr/bin/env python3
"""Video retrieval probe: sends the generated test clip, checks planted codes."""
import json,os,time,urllib.request,urllib.error
D=os.path.dirname(os.path.abspath(__file__))
URL=os.environ.get("TARGET_URL","http://127.0.0.1:8080/v1/chat/completions")
MODEL=os.environ.get("TARGET_MODEL","qwen3.8-27b")
try: KEY=open(os.path.join(D,"api-key.txt")).read().strip()
except Exception: KEY=""
H={"Content-Type":"application/json"}
if KEY: H["Authorization"]="Bearer "+KEY
b64=open(os.environ.get("VID_B64","/opt/ninfer/testvid.b64")).read().strip()
codes=[l.strip() for l in open(os.environ.get("VID_CODES","/opt/ninfer/testvid.codes")) if l.strip()]
print("clip: %d KB base64, %d planted codes"%(len(b64)//1024,len(codes)))
body=dict(model=MODEL,max_tokens=1500,temperature=1.0,reasoning_effort="medium",
  messages=[{"role":"user","content":[
    {"type":"video_url","video_url":{"url":"data:video/mp4;base64,"+b64}},
    {"type":"text","text":"This video shows a sequence of numbered segments, each displaying a CODE. List every CODE value you can read, in order."}]}])
req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers=H)
t0=time.time()
try:
    r=json.load(urllib.request.urlopen(req,timeout=600)); dt=time.time()-t0
    c=r["choices"][0]["message"].get("content") or ""
    u=r.get("usage",{})
    found=sum(1 for k in codes if k in c)
    print("VIDEO wall=%.1fs prompt_tok=%s found=%d/%d"%(dt,u.get("prompt_tokens"),found,len(codes)))
    print("reply: "+c.replace("\n"," ")[:220])
except urllib.error.HTTPError as e:
    print("VIDEO -> HTTP %s %s"%(e.code,e.read().decode()[:180]))
except Exception as e:
    print("VIDEO -> %s"%str(e)[:180])
print("VIDPROBE_DONE")
