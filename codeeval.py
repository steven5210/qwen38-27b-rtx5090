#!/usr/bin/env python3
"""Objective coding-quality eval: unit-tested problems + tool-call validity + long-context bug hunt.
Usage: codeeval.py --tag A --samples 3
Scores are pass/fail against real test suites, not judgement calls."""
import argparse, json, os, re, subprocess, sys, tempfile, time, urllib.request

KEY = open('/opt/qwen38/api-key.txt').read().strip()
URL = "http://127.0.0.1:8000/v1/chat/completions"

def chat(messages, max_tokens=6000, effort="medium", tools=None, seed=None, temp=1.0):
    body = {"model":"qwen3.8-27b","messages":messages,"max_tokens":max_tokens,
            "temperature":temp,"top_p":0.95,"reasoning_effort":effort}
    if seed is not None: body["seed"]=seed
    if tools: body["tools"]=tools; body["tool_choice"]="auto"
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {KEY}"})
    t0=time.perf_counter()
    r=json.load(urllib.request.urlopen(req,timeout=900))
    ch=r["choices"][0]
    return {"content":ch["message"].get("content") or "", "tool_calls":ch["message"].get("tool_calls"),
            "finish":ch.get("finish_reason"), "tokens":r["usage"]["completion_tokens"],
            "secs":round(time.perf_counter()-t0,1)}

def extract_code(text):
    m=re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    if m: return max(m, key=len)
    return text

def run_tests(code, tests):
    src = code + "\n\n" + tests + "\n\nprint('__PASS__')\n"
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
        f.write(src); path=f.name
    try:
        p=subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=30)
        return "__PASS__" in p.stdout, (p.stderr or "")[-200:]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    finally:
        os.unlink(path)

PROBLEMS = [
 dict(name="merge_intervals",
   prompt="Write a Python function `merge_intervals(intervals)` that merges overlapping intervals. Input is a list of [start,end] lists, output a new sorted list of merged [start,end]. Touching intervals like [1,2] and [2,3] DO merge. Handle empty input. Output ONLY a python code block.",
   tests="""
assert merge_intervals([]) == []
assert merge_intervals([[1,3],[2,6],[8,10]]) == [[1,6],[8,10]]
assert merge_intervals([[1,2],[2,3]]) == [[1,3]]
assert merge_intervals([[5,6],[1,2]]) == [[1,2],[5,6]]
assert merge_intervals([[1,10],[2,3],[4,5]]) == [[1,10]]
assert merge_intervals([[1,4],[5,6]]) == [[1,4],[5,6]]
"""),
 dict(name="version_compare",
   prompt="Write a Python function `compare_versions(a, b)` returning -1, 0, or 1 comparing semantic version strings. Support pre-release suffixes: 1.0.0-alpha < 1.0.0. Numeric segments compare numerically ('1.10' > '1.9'). Missing segments count as 0 ('1.0' == '1.0.0'). Output ONLY a python code block.",
   tests="""
assert compare_versions('1.0.0','1.0.0')==0
assert compare_versions('1.10.0','1.9.0')==1
assert compare_versions('1.0','1.0.0')==0
assert compare_versions('1.0.0-alpha','1.0.0')==-1
assert compare_versions('2.0.0','10.0.0')==-1
assert compare_versions('1.0.1','1.0.0')==1
"""),
 dict(name="toposort",
   prompt="Write a Python function `topo_sort(graph)` where graph is a dict mapping node -> list of nodes it depends on. Return a list ordering nodes so dependencies come first. Ties broken alphabetically for determinism. Raise ValueError('cycle') if there is a cycle. Output ONLY a python code block.",
   tests="""
assert topo_sort({'a':[],'b':['a'],'c':['b']}) == ['a','b','c']
assert topo_sort({'b':['a'],'a':[],'c':['a']}) == ['a','b','c']
try:
    topo_sort({'a':['b'],'b':['a']}); raise AssertionError('should raise')
except ValueError: pass
assert topo_sort({}) == []
"""),
 dict(name="token_bucket",
   prompt="Write a Python class `TokenBucket(capacity, refill_per_sec)` with method `allow(now, cost=1)` returning True/False. `now` is a float timestamp passed in (do NOT call time functions). Bucket starts full, refills continuously at refill_per_sec up to capacity, and allow() consumes cost tokens only if available. Output ONLY a python code block.",
   tests="""
b=TokenBucket(2,1)
assert b.allow(0.0)==True
assert b.allow(0.0)==True
assert b.allow(0.0)==False
assert b.allow(1.0)==True
assert b.allow(1.0)==False
b2=TokenBucket(5,2)
assert b2.allow(0.0,cost=5)==True
assert b2.allow(0.0,cost=1)==False
assert b2.allow(10.0,cost=5)==True
"""),
 dict(name="apply_patch",
   prompt="Write a Python function `apply_hunks(lines, hunks)`. `lines` is a list of strings. `hunks` is a list of dicts {'start': int (0-based index), 'remove': int, 'insert': list_of_strings}. Apply ALL hunks to produce a new list. Hunk indices refer to positions in the ORIGINAL list, so applying multiple hunks must not shift each other incorrectly. Output ONLY a python code block.",
   tests="""
assert apply_hunks(['a','b','c'], [{'start':1,'remove':1,'insert':['X']}]) == ['a','X','c']
assert apply_hunks(['a','b','c'], [{'start':0,'remove':0,'insert':['Z']}]) == ['Z','a','b','c']
assert apply_hunks(['a','b','c','d'], [{'start':0,'remove':1,'insert':['X','Y']},{'start':3,'remove':1,'insert':[]}]) == ['X','Y','b','c']
assert apply_hunks(['a'], []) == ['a']
"""),
 dict(name="lru_ttl",
   prompt="Write a Python class `LRUTTLCache(capacity)` with `get(key, now)` and `put(key, value, now, ttl)`. Entries expire when now >= insert_time+ttl (expired entries must behave as missing and return None). When capacity is exceeded, evict the least-recently-used non-expired entry. `get` counts as a use. Do NOT call time functions. Output ONLY a python code block.",
   tests="""
c=LRUTTLCache(2)
c.put('a',1,0.0,10); c.put('b',2,0.0,10)
assert c.get('a',1.0)==1
c.put('c',3,1.0,10)          # evicts b (a was just used)
assert c.get('b',1.0) is None
assert c.get('a',1.0)==1
assert c.get('c',1.0)==3
c2=LRUTTLCache(2)
c2.put('x',1,0.0,5)
assert c2.get('x',6.0) is None
"""),
 dict(name="json_path",
   prompt="Write a Python function `jpath(obj, path)` supporting dot notation and list indices, e.g. 'a.b[0].c'. Return None if any part is missing rather than raising. Output ONLY a python code block.",
   tests="""
d={'a':{'b':[{'c':7}]},'n':None}
assert jpath(d,'a.b[0].c')==7
assert jpath(d,'a.b[1].c') is None
assert jpath(d,'a.x.y') is None
assert jpath(d,'n') is None
assert jpath({'k':[1,2,3]},'k[2]')==3
"""),
 dict(name="wildcard_match",
   prompt="Write a Python function `wildcard(pattern, text)` returning True/False. '*' matches any sequence including empty; '?' matches exactly one character. Must handle long inputs without exponential blowup. Output ONLY a python code block.",
   tests="""
assert wildcard('a*c','abc')==True
assert wildcard('a?c','abc')==True
assert wildcard('a?c','ac')==False
assert wildcard('*','')==True
assert wildcard('','')==True
assert wildcard('','a')==False
assert wildcard('*a*b*','xxayybzz')==True
assert wildcard('a*b','a'+'x'*2000+'c')==False
"""),
]

TOOLS=[{"type":"function","function":{"name":"write_file","description":"Write content to a file",
  "parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},
  "required":["path","content"]}}}]

def tool_test(seed):
    msgs=[{"role":"user","content":"Create a file named config/app.json containing a JSON object with keys \"name\" (string \"demo\") and \"retries\" (number 3). Use the write_file tool. The content must include real newlines and quotes."}]
    r=chat(msgs, max_tokens=3000, tools=TOOLS, seed=seed)
    tc=r.get("tool_calls")
    if not tc: return False,"no tool_call"
    try:
        args=json.loads(tc[0]["function"]["arguments"])
    except Exception as e:
        return False,f"bad JSON args: {str(e)[:80]}"
    if "path" not in args or "content" not in args: return False,"missing fields"
    try: json.loads(args["content"])
    except Exception: return False,"content not valid JSON"
    return True,"ok"

def longctx_test(seed, target=40000):
    blk=("def svc_%d(req):\n    payload = req.json()\n    validate(payload)\n    return dispatch(payload, retries=3)\n\n")
    n=max(1,target//45)
    parts=[blk%i for i in range(n)]
    bug_at=n//2
    parts[bug_at]=("def svc_%d(req):\n    payload = req.json()\n    validate(payload)\n"
                   "    return dispatch(payload, retries=-1)   # <-- differs from every other handler\n\n")%bug_at
    src="".join(parts)
    msgs=[{"role":"user","content":"Below is a module where every handler is identical except ONE, which passes a different retries value.\n```python\n"+src+"```\nReply with ONLY the name of that one function (e.g. svc_123)."}]
    r=chat(msgs,max_tokens=2500,effort="medium",seed=seed)
    want=f"svc_{bug_at}"
    return (want in r["content"]), f"want {want}, got {r['content'][-60:].strip()!r}"

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--tag",required=True); ap.add_argument("--samples",type=int,default=3)
    a=ap.parse_args()
    res={"tag":a.tag,"samples":a.samples,"problems":{},"totals":{}}
    passes=total=0
    for p in PROBLEMS:
        ok_n=0; detail=[]
        for s in range(a.samples):
            try:
                r=chat([{"role":"user","content":p["prompt"]}], seed=1000+s)
                ok,err=run_tests(extract_code(r["content"]), p["tests"])
            except Exception as e:
                ok,err=False,str(e)[:100]; r={"tokens":0,"secs":0,"finish":"err"}
            ok_n+=ok; total+=1; passes+=ok
            detail.append({"ok":ok,"err":"" if ok else err,"tok":r.get("tokens"),"s":r.get("secs"),"finish":r.get("finish")})
        res["problems"][p["name"]]={"pass":ok_n,"of":a.samples,"runs":detail}
        print(f"{p['name']}: {ok_n}/{a.samples}", flush=True)
    tools_ok=0
    for s in range(a.samples):
        ok,msg=tool_test(2000+s); tools_ok+=ok
        print(f"tool_call[{s}]: {'PASS' if ok else 'FAIL '+msg}", flush=True)
    lc_ok=0
    for s in range(2):
        ok,msg=longctx_test(3000+s); lc_ok+=ok
        print(f"longctx[{s}]: {'PASS' if ok else 'FAIL '+msg}", flush=True)
    res["totals"]={"code_pass":passes,"code_total":total,
                   "code_pct":round(100*passes/total,1) if total else 0,
                   "tool_pass":tools_ok,"tool_total":a.samples,
                   "longctx_pass":lc_ok,"longctx_total":2}
    print(json.dumps(res["totals"],indent=1))
    json.dump(res,open(f"/mnt/c/Users/StevenPC/Downloads/qwen38/codeeval_{a.tag}.json","w"),indent=1)
    print("EVAL_DONE")

if __name__=="__main__":
    main()
