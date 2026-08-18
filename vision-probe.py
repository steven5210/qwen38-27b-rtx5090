#!/usr/bin/env python3
"""Does the server actually SEE images, and what does an image cost in tokens/time?"""
import base64, io, json, os, sys, time, urllib.request
BASE="http://127.0.0.1:8000"; KEY=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"api-key.txt")).read().strip()
def post(p,d,t=600):
    r=urllib.request.Request(BASE+p,data=json.dumps(d).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})
    return json.loads(urllib.request.urlopen(r,timeout=t).read().decode())

def make_png(text_lines, w=760, h=420):
    from PIL import Image, ImageDraw
    img=Image.new("RGB",(w,h),(250,250,250)); d=ImageDraw.Draw(img)
    y=18
    for ln in text_lines:
        d.text((16,y), ln, fill=(15,15,15)); y+=22
    b=io.BytesIO(); img.save(b,format="PNG"); return base64.b64encode(b.getvalue()).decode()

# A screenshot-like image: a stack trace with a specific, checkable value.
CODE=["Traceback (most recent call last):",
      '  File "app/handlers/billing.py", line 148, in settle',
      "    total = compute(invoice, rate=RATE_TABLE[tier])",
      "KeyError: 'enterprise_plus'",
      "",
      "RATE_TABLE keys: basic, pro, enterprise",
      "invoice.id = INV-90431   tier = enterprise_plus",
      "retry_after_ms = 8250"]
def main():
    b64=make_png(CODE)
    t0=time.time()
    r=post("/v1/chat/completions", dict(model="qwen3.8-27b", temperature=1.0, max_tokens=900,
        messages=[{"role":"user","content":[
            {"type":"image_url","image_url":{"url":"data:image/png;base64,"+b64}},
            {"type":"text","text":"This is a screenshot of an error. Answer with exactly two lines:\n"
                                  "LINE1: the exact value of retry_after_ms\n"
                                  "LINE2: the exact missing key named in the KeyError"}]}]))
    dt=time.time()-t0
    m=r["choices"][0]["message"]; c=(m.get("content") or "")
    u=r.get("usage",{})
    ok_val = "8250" in c
    ok_key = "enterprise_plus" in c
    print("VISION_REQUEST ok=%s secs=%.1f prompt_tok=%s out_tok=%s"
          % (r.get("id") is not None, dt, u.get("prompt_tokens"), u.get("completion_tokens")))
    print("  reads retry_after_ms=8250 : %s" % ok_val)
    print("  reads key enterprise_plus : %s" % ok_key)
    print("  reply: %s" % c.strip().replace("\n"," | ")[:160])
    print("VISION_SCORE %d/2" % (int(ok_val)+int(ok_key)))
if __name__=="__main__":
    try: main()
    except Exception as e:
        print("VISION_REQUEST FAILED: %s: %s" % (type(e).__name__, str(e)[:300]))
        print("VISION_SCORE 0/2")
