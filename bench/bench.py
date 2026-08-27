#!/usr/bin/env python3
"""Coding-shaped benchmark for the local Qwen3.8-27B server."""
import argparse, concurrent.futures, json, os, time, urllib.request

def stream_chat(url, key, model, messages, max_tokens=512, temperature=0.7, think=True):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "top_p": 0.95, "stream": True,
            "stream_options": {"include_usage": True}}
    if not think:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(url + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {key}"} if key else {})})
    t0 = time.perf_counter(); ttft = None; chunks = 0; usage = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"): continue
            data = line[5:].strip()
            if data == "[DONE]": break
            obj = json.loads(data)
            if obj.get("usage"): usage = obj["usage"]
            ch = obj.get("choices") or []
            if ch:
                d = ch[0].get("delta") or {}
                if d.get("content") or d.get("reasoning_content"):
                    if ttft is None: ttft = time.perf_counter() - t0
                    chunks += 1
    total = time.perf_counter() - t0
    out_tokens = (usage or {}).get("completion_tokens") or chunks
    prompt_tokens = (usage or {}).get("prompt_tokens")
    decode_s = total - (ttft or 0)
    return {"ttft_s": round(ttft or 0, 3), "total_s": round(total, 2),
            "prompt_tokens": prompt_tokens, "out_tokens": out_tokens,
            "decode_tok_s": round(out_tokens / decode_s, 1) if decode_s > 0 else None}

CODE_PROMPT = ("Write a Python function `merge_intervals(intervals)` that merges overlapping "
               "intervals, with type hints, docstring, and 5 pytest cases. Code only.")

def big_context_messages(target_tokens=8000):
    block = ("def handler_%d(req):\n    # validate, transform, persist\n"
             "    data = req.json()\n    if not data.get('id'):\n        raise ValueError('missing id')\n"
             "    return {'ok': True, 'id': data['id']}\n\n")
    n = max(1, target_tokens // 45)
    src = "".join(block % i for i in range(n))
    return [{"role": "user", "content": "Here is a module:\n```python\n" + src +
             "```\nRefactor the repeated handlers into one generic function and show the final code."}]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--key", default=os.environ.get("VLLM_API_KEY", ""))
    ap.add_argument("--model", default="qwen3.8-27b")
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()
    R = {"tag": a.tag}
    print("warmup...", flush=True)
    stream_chat(a.url, a.key, a.model, [{"role":"user","content":"hi"}], max_tokens=16, think=False)
    print("1/4 short coding, thinking OFF...", flush=True)
    R["short_nothink"] = stream_chat(a.url, a.key, a.model, [{"role":"user","content":CODE_PROMPT}], max_tokens=700, temperature=0.7, think=False)
    print("2/4 short coding, thinking ON...", flush=True)
    R["short_think"] = stream_chat(a.url, a.key, a.model, [{"role":"user","content":CODE_PROMPT}], max_tokens=2000, temperature=1.0, think=True)
    print("3/4 ~8K-context refactor (prefill)...", flush=True)
    R["ctx8k"] = stream_chat(a.url, a.key, a.model, big_context_messages(), max_tokens=700, think=False)
    print("4/4 4-way concurrent burst...", flush=True)
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(lambda _: stream_chat(a.url, a.key, a.model,
                    [{"role":"user","content":CODE_PROMPT}], max_tokens=300, think=False), range(4)))
    wall = time.perf_counter() - t0
    agg = sum(r["out_tokens"] for r in rs)
    R["concurrent4"] = {"wall_s": round(wall,2), "total_out_tokens": agg,
                        "aggregate_tok_s": round(agg/wall,1),
                        "per_stream": [r["decode_tok_s"] for r in rs]}
    print(json.dumps(R, indent=2))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"bench_{a.tag}.json")
    with open(out,"w") as f: json.dump(R,f,indent=2)
    print("saved ->", out)

if __name__ == "__main__":
    main()
