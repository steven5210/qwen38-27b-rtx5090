#!/usr/bin/env python3
"""bench2.py - spec-depth decision benchmark. Workloads shaped like real Cline traffic.
Usage: bench2.py --tag spec3"""
import argparse, concurrent.futures, json, os, time, urllib.request

KEY = open('/opt/qwen38/api-key.txt').read().strip()
URL = "http://127.0.0.1:8000/v1/chat/completions"

def chat(messages, max_tokens, effort=None, think=True, seed=None, temperature=1.0):
    body = {"model": "qwen3.8-27b", "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "top_p": 0.95, "stream": True,
            "stream_options": {"include_usage": True}}
    if seed is not None: body["seed"] = seed
    if effort: body["reasoning_effort"] = effort
    if not think: body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    t0 = time.perf_counter(); ttft = None; usage = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"): continue
            d = line[5:].strip()
            if d == "[DONE]": break
            o = json.loads(d)
            if o.get("usage"): usage = o["usage"]
            ch = o.get("choices") or []
            if ch:
                de = ch[0].get("delta") or {}
                if (de.get("content") or de.get("reasoning_content")) and ttft is None:
                    ttft = time.perf_counter() - t0
    total = time.perf_counter() - t0
    out = (usage or {}).get("completion_tokens") or 0
    dec = total - (ttft or 0)
    return {"ttft": round(ttft or 0, 2), "total": round(total, 1), "out_tok": out,
            "tok_s": round(out / dec, 1) if dec > 0 and out else 0}

CODE_Q = "Write a Python function `merge_intervals(intervals)` merging overlapping intervals, with type hints, docstring, 5 pytest cases. Code only."
HARD_Q = "Design a thread-safe LRU cache with per-entry TTL in Python. Handle the expiry/access race, justify locking granularity, give the full implementation."

def big_ctx(target=30000):
    block = ("def handler_%d(req):\n    data = req.json()\n    if not data.get('id'):\n        raise ValueError('missing id')\n    audit_log(req.user, data)\n    return {'ok': True, 'id': data['id']}\n\n")
    n = max(1, target // 55)
    src = "".join(block % i for i in range(n))
    return [{"role": "user", "content": "Module:\n```python\n" + src + "```\nExplain the biggest design flaw and refactor it. Show final code."}]

def mean(xs): return round(sum(xs)/len(xs), 1) if xs else 0

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    R = {"tag": a.tag, "ts": time.strftime("%H:%M:%S")}
    chat([{"role":"user","content":"hi"}], 16, think=False)  # warmup

    s1 = [chat([{"role":"user","content":CODE_Q}], 600, think=False, seed=100+i) for i in range(3)]
    R["S1_short_nothink"] = {"tok_s": mean([x["tok_s"] for x in s1]), "runs": [x["tok_s"] for x in s1]}

    s2 = [chat([{"role":"user","content":HARD_Q}], 3000, effort="medium", seed=200+i) for i in range(2)]
    R["S2_medium_think"] = {"tok_s": mean([x["tok_s"] for x in s2]), "out": [x["out_tok"] for x in s2],
                            "total_s": [x["total"] for x in s2]}

    ctx = big_ctx()
    s3 = [chat(ctx, 2000, effort="medium", seed=300+i) for i in range(2)]
    R["S3_ctx30k_think"] = {"tok_s": mean([x["tok_s"] for x in s3]), "ttft_first": s3[0]["ttft"],
                            "ttft_cached": s3[1]["ttft"], "out": [x["out_tok"] for x in s3]}

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(lambda i: chat([{"role":"user","content":CODE_Q}], 300, think=False, seed=400+i), range(4)))
    wall = time.perf_counter() - t0
    agg = sum(r["out_tok"] for r in rs)
    R["S4_concurrent4"] = {"aggregate_tok_s": round(agg/wall, 1), "per_stream": [r["tok_s"] for r in rs]}

    print(json.dumps(R, indent=1))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"bench2_{a.tag}.json"), "w") as f:
        json.dump(R, f, indent=1)

if __name__ == "__main__":
    main()
