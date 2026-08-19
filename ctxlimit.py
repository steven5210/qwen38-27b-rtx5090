#!/usr/bin/env python3
"""Where exactly does vLLM reject? Is max_model_len a prompt cap or a prompt+output cap?"""
import json, os, sys, urllib.request, urllib.error
BASE="http://127.0.0.1:8000"
KEY=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"api-key.txt")).read().strip()
def post(p,d,t=900):
    r=urllib.request.Request(BASE+p,data=json.dumps(d).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})
    try:
        return json.loads(urllib.request.urlopen(r,timeout=t).read().decode()), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()[:400]

sys.path.insert(0,"/opt/qwen38/venv/lib/python3.12/site-packages")
from transformers import AutoTokenizer
import glob
snap=glob.glob('/opt/qwen38/hf/hub/models--unsloth--Qwen3.8-27B-NVFP4/snapshots/*/')[0]
tk=AutoTokenizer.from_pretrained(snap, trust_remote_code=True)

# realistic code filler
UNIT='''
def process_batch_%d(records, cfg, *, retries=3, timeout=30.0):
    """Normalise and persist a batch of records."""
    out = []
    for rec in records:
        if not rec.get("id"):
            log.warning("skipping record without id: %%r", rec)
            continue
        payload = {"id": rec["id"], "ts": rec.get("ts", now()), "tier": rec.get("tier","basic")}
        for attempt in range(retries):
            try:
                out.append(client.put(payload, timeout=timeout)); break
            except TransientError as exc:
                if attempt == retries - 1: raise
                sleep(BACKOFF_MS * (2 ** attempt) / 1000.0)
    return out
'''
def make_prompt(target_tokens):
    body, i = [], 0
    while True:
        body.append(UNIT % i); i += 1
        if i % 20 == 0:
            n=len(tk.encode("".join(body), add_special_tokens=False))
            if n >= target_tokens: break
    txt="".join(body)
    ids=tk.encode(txt, add_special_tokens=False)
    return tk.decode(ids[:target_tokens]), len(ids[:target_tokens])

MML=int(os.environ.get("MML","98304"))
print("MAX_MODEL_LEN configured = %d\n" % MML)
CEIL = MML - 16384
CASES = [(CEIL - 800, 16384), (CEIL + 800, 16384), (MML - 3000, 2048)]
for prompt_tok, max_out in CASES:
    p, actual = make_prompt(prompt_tok)
    r, err = post("/v1/chat/completions", dict(model="qwen3.8-27b", max_tokens=max_out,
        temperature=1.0, messages=[{"role":"user","content":p+"\n\nReply with the single word OK."}]))
    if r:
        u=r.get("usage",{})
        print("prompt~%-6d + max_tokens=%-6d -> ACCEPTED (prompt_tokens=%s, sum=%s)"
              % (actual, max_out, u.get("prompt_tokens"), (u.get("prompt_tokens") or 0)+max_out))
    else:
        print("prompt~%-6d + max_tokens=%-6d -> REJECTED: %s"
              % (actual, max_out, " ".join(err.split())[:230]))
print("\nExpected hard prompt ceiling at max_tokens=16384: %d" % CEIL)
print("CTXLIMIT_DONE")
