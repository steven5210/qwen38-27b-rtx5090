#!/usr/bin/env python3
"""Replicate the EXACT original vision-probe request 6x: is the flake thinking-budget truncation?"""
import base64, io, json, os, urllib.request
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
CODE=["Traceback (most recent call last):",
      '  File "app/handlers/billing.py", line 148, in settle',
      "    total = compute(invoice, rate=RATE_TABLE[tier])",
      "KeyError: 'enterprise_plus'",
      "",
      "RATE_TABLE keys: basic, pro, enterprise",
      "invoice.id = INV-90431   tier = enterprise_plus",
      "retry_after_ms = 8250"]
b64=make_png(CODE)
body=dict(model="qwen3.8-27b", temperature=1.0, max_tokens=900,
    messages=[{"role":"user","content":[
        {"type":"image_url","image_url":{"url":"data:image/png;base64,"+b64}},
        {"type":"text","text":"This is a screenshot of an error. Answer with exactly two lines:\n"
                              "LINE1: the exact value of retry_after_ms\nLINE2: the exact missing key named in the KeyError"}]}])
for i in range(6):
    r=post(body); ch=r["choices"][0]; m=ch["message"]; u=r.get("usage",{})
    c=(m.get("content") or ""); th=len(m.get("reasoning_content") or "")
    score=int("8250" in c)+int("enterprise_plus" in c)
    print("run%d  finish=%-12s out=%-4s think_chars=%-5s score=%d/2  empty_content=%s"
          %(i+1,ch.get("finish_reason"),u.get("completion_tokens"),th,score,not c.strip()))
print("VREP2_DONE")
