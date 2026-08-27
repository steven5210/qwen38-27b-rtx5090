#!/usr/bin/env python3
"""Does vLLM's thinking_token_budget rescue xhigh, and does it corrupt tool calls?

Context: our own measurement showed xhigh fails purely by TRUNCATION (finish_reason=length),
never by wrong answers. If the thinking can be capped, the model is forced to stop reasoning
and write the answer -- which should convert those failures into passes.

Risk: vLLM issue #44676 -- ThinkingBudgetStateHolder does not treat <tool_call> as an implicit
reasoning end, so with tools it can keep counting ARGUMENT tokens against the thinking budget
and then inject the reasoning-end string into the middle of the JSON. Confirmed present in
this build (0 occurrences of 'tool_call' in thinking_budget_state.py).
"""
import os, sys, json, time, importlib.util, urllib.request, urllib.error
D="/mnt/c/Users/StevenPC/Downloads/qwen38"
KEY=open(os.path.join(D,"api-key.txt")).read().strip()
URL="http://127.0.0.1:8000/v1/chat/completions"
spec=importlib.util.spec_from_file_location("ce", os.path.join(D,"codeeval.py"))
ce=importlib.util.module_from_spec(spec); spec.loader.exec_module(ce)
PROBS={p["name"]:p for p in ce.PROBLEMS}

def call(body):
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})
    t0=time.time()
    try:
        r=json.load(urllib.request.urlopen(req,timeout=900))
        ch=r["choices"][0]
        return dict(ok=True, secs=round(time.time()-t0,1), finish=ch.get("finish_reason"),
                    content=ch["message"].get("content") or "",
                    reasoning=ch["message"].get("reasoning_content") or "",
                    tool_calls=ch["message"].get("tool_calls"),
                    tokens=r["usage"]["completion_tokens"],
                    rtok=(r["usage"].get("completion_tokens_details") or {}).get("reasoning_tokens"))
    except urllib.error.HTTPError as e:
        return dict(ok=False, err="HTTP %s %s" % (e.code," ".join(e.read().decode().split())[:200]))

print("### 1. is thinking_token_budget accepted at all? ###")
r=call(dict(model="qwen3.8-27b", max_tokens=2000, temperature=1.0, thinking_token_budget=300,
            reasoning_effort="xhigh",
            messages=[{"role":"user","content":"Prove there are infinitely many primes. Be rigorous."}]))
if not r["ok"]:
    print("  REJECTED:", r["err"]); print("THINKTEST_DONE"); sys.exit(0)
print("  accepted. finish=%s total_tokens=%d thinking_chars=%d answer_chars=%d"
      % (r["finish"], r["tokens"], len(r["reasoning"]), len(r["content"])))
r2=call(dict(model="qwen3.8-27b", max_tokens=2000, temperature=1.0, reasoning_effort="xhigh",
            messages=[{"role":"user","content":"Prove there are infinitely many primes. Be rigorous."}]))
print("  same prompt, NO budget: finish=%s total=%d thinking_chars=%d answer_chars=%d"
      % (r2["finish"], r2["tokens"], len(r2["reasoning"]), len(r2["content"])))
capped = len(r["reasoning"]) < len(r2["reasoning"]) * 0.8
print("  -> budget %s" % ("IS capping thinking" if capped else "had NO visible effect"))

print("\n### 2. does it rescue the problems xhigh truncated? (budget 2500, max_tokens 8000) ###")
tot=ok=0
for name in ["lru_ttl","wildcard_match","apply_patch","json_path"]:
    p=PROBS[name]
    for i in range(2):
        r=call(dict(model="qwen3.8-27b", max_tokens=8000, temperature=1.0, top_p=0.95,
                    reasoning_effort="xhigh", thinking_token_budget=2500, seed=700+i,
                    messages=[{"role":"user","content":p["prompt"]}]))
        if not r["ok"]: print("  %-15s s%d ERROR %s" % (name,i,r["err"])); continue
        good,err=ce.run_tests(ce.extract_code(r["content"]), p["tests"])
        tot+=1; ok+=1 if good else 0
        print("  %-15s s%d %-4s finish=%-7s tokens=%-6d %5.0fs think_chars=%-6d %s"
              % (name,i,"OK" if good else "FAIL",r["finish"],r["tokens"],r["secs"],
                 len(r["reasoning"]), "" if good else err.strip().replace("\n"," ")[:45]), flush=True)
print("  --> %d/%d  (these were 0/2 or 1/2 at xhigh with NO budget, even at 16384 tokens)" % (ok,tot))

print("\n### 3. does it corrupt tool calls? (vLLM #44676) ###")
TOOLS=[{"type":"function","function":{"name":"write_file","description":"Write a file.",
  "parameters":{"type":"object","properties":{
    "path":{"type":"string"},"content":{"type":"string"},"mode":{"type":"string"}},
    "required":["path","content"]}}}]
bad=0; n=0
for i in range(8):
    r=call(dict(model="qwen3.8-27b", max_tokens=3000, temperature=1.0, tools=TOOLS,
                tool_choice="auto", reasoning_effort="xhigh", thinking_token_budget=200, seed=900+i,
                messages=[{"role":"user","content":
                  "Carefully decide the right approach, then write a file at src/config/%d.json "
                  "containing a JSON object with keys retries=5, timeout_ms=30000, and a "
                  "long description field explaining the retry policy in at least 3 sentences. "
                  "Use the tool." % i}]))
    n+=1
    if not r["ok"]: print("  call %d ERROR %s" % (i,r["err"])); bad+=1; continue
    tc=r["tool_calls"] or []
    status="no_tool_call"
    if tc:
        raw=tc[0]["function"]["arguments"]
        try:
            a=json.loads(raw)
            status="valid json, keys=%s" % sorted(a)[:4]
        except Exception as e:
            status="CORRUPT JSON: %s | raw tail: %r" % (str(e)[:40], raw[-70:]); bad+=1
    else:
        bad+=1
    print("  call %d finish=%-7s %s" % (i, r["finish"], status), flush=True)
print("  --> %d/%d calls problematic" % (bad,n))
print("THINKTEST_DONE")
