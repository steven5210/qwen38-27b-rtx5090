#!/usr/bin/env python3
"""Repeated-vision-request investigation: is the second identical request broken, and on which path?"""
import base64, io, json, os, time, urllib.request
BASE=os.environ.get("QWEN_URL","http://127.0.0.1:8080")
KEY=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"api-key.txt")).read().strip()
def post(d,t=300):
    r=urllib.request.Request(BASE+"/v1/chat/completions",data=json.dumps(d).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})
    return json.loads(urllib.request.urlopen(r,timeout=t).read().decode())
def make_png(lines,w=760,h=420):
    from PIL import Image, ImageDraw
    img=Image.new("RGB",(w,h),(250,250,250)); d=ImageDraw.Draw(img); y=18
    for ln in lines: d.text((16,y),ln,fill=(15,15,15)); y+=22
    b=io.BytesIO(); img.save(b,format="PNG"); return base64.b64encode(b.getvalue()).decode()
IMG1=make_png(["ALPHA CODE: 7371","BETA KEY: crimson_falcon"])
IMG2=make_png(["ALPHA CODE: 2846","BETA KEY: silver_otter"])
def vreq(img,text,effort):
    body=dict(model="qwen3.8-27b",max_tokens=900,
        messages=[{"role":"user","content":[
            {"type":"image_url","image_url":{"url":"data:image/png;base64,"+img}},
            {"type":"text","text":text}]}])
    if effort: body["reasoning_effort"]=effort
    return post(body)
def treq(text,effort="none"):
    return post(dict(model="qwen3.8-27b",max_tokens=200,reasoning_effort=effort,
        messages=[{"role":"user","content":text}]))
def show(tag,r):
    ch=r["choices"][0]; m=ch["message"]; u=r.get("usage",{})
    ptd=(u.get("prompt_tokens_details") or {}).get("cached_tokens")
    print("%-14s finish=%-12s prompt=%-5s cached=%-5s out=%-4s think_len=%-5s content=%r"
          %(tag,ch.get("finish_reason"),u.get("prompt_tokens"),ptd,u.get("completion_tokens"),
            len(m.get("reasoning_content") or ""),(m.get("content") or "")[:110]))
Q="Answer with exactly two lines:\nLINE1: the ALPHA CODE value\nLINE2: the BETA KEY value"
print("== phase 1: effort=none (isolates reuse from thinking budget)")
show("T1",treq("Reply with exactly the word: checkpoint-alpha"))
show("T1-repeat",treq("Reply with exactly the word: checkpoint-alpha"))
show("V1",vreq(IMG1,Q,"none"))
show("V2=V1 repeat",vreq(IMG1,Q,"none"))
show("V3=V1 repeat",vreq(IMG1,Q,"none"))
show("V4 same-img newQ",vreq(IMG1,"What color is the background? One word.","none"))
show("V5 new-img",vreq(IMG2,Q,"none"))
print("== phase 2: default effort (original probe condition, max_tokens=900)")
show("W1",vreq(IMG1,Q,None))
show("W2=W1 repeat",vreq(IMG1,Q,None))
show("W3=W1 repeat",vreq(IMG1,Q,None))
print("VREP_DONE")
