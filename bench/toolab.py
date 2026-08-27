#!/usr/bin/env python3
"""Tool-call reliability A/B: n=20 write_file calls across 5 content shapes.
Target server via TARGET_URL / TARGET_MODEL env."""
import json,os,time,urllib.request,urllib.error
D=os.path.dirname(os.path.abspath(__file__))
URL=os.environ.get("TARGET_URL","http://127.0.0.1:8000/v1/chat/completions")
MODEL=os.environ.get("TARGET_MODEL","qwen3.8-27b")
try: KEY=open(os.path.join(D,"api-key.txt")).read().strip()
except Exception: KEY=""
def call(body):
    h={"Content-Type":"application/json"}
    if KEY: h["Authorization"]="Bearer "+KEY
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers=h)
    try:
        r=json.load(urllib.request.urlopen(req,timeout=300))
        m=r["choices"][0]["message"]
        return dict(ok=True,tc=m.get("tool_calls"),content=m.get("content") or "")
    except urllib.error.HTTPError as e:
        return dict(ok=False,err="HTTP %s %s"%(e.code,e.read().decode()[:100]))
    except Exception as e:
        return dict(ok=False,err=str(e)[:100])
TOOLS=[{"type":"function","function":{"name":"write_file","description":"Write content to a file",
 "parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},
 "required":["path","content"]}}}]
def chk_json(c):
    try: json.loads(c); return True,"ok"
    except Exception as e: return False,"content not JSON: %s"%str(e)[:38]
def chk_py(c):
    try: compile(c,"x","exec"); return True,"ok"
    except Exception as e: return False,"py: %s"%str(e)[:38]
def chk_sh(c):
    ok=c.strip().startswith("#!") and "echo" in c
    return ok,"ok" if ok else "missing shebang/echo"
def chk_md(c):
    ok=c.count("#")>=2 and "```" in c
    return ok,"ok" if ok else "missing headers/fence"
V=[("nested-json",'Create config/app.json: a JSON object with keys "name" ("demo"), "retries" (3), and "notes" (a string that itself contains a double-quoted word and a real newline). Use write_file.',chk_json),
   ("python",'Create util/dates.py: a Python module with a docstring, an f-string, and a function days_between(a,b) using datetime. Use write_file.',chk_py),
   ("json-newlines",'Create data/msg.json: a JSON object with key "body" whose string value contains three lines separated by real newlines and a quoted phrase. Use write_file.',chk_json),
   ("shell",'Create bin/backup.sh: a bash script with a shebang, a quoted path containing spaces, and an echo with a double-quoted message. Use write_file.',chk_sh),
   ("markdown",'Create docs/note.md: markdown with two headers, a fenced python code block containing a quoted string, and a bullet list. Use write_file.',chk_md)]
N=int(os.environ.get("TOOL_N","20")); per=N//len(V)
res={}; fails=[]; tot=okn=0
for name,prompt,chk in V:
    v=0
    for i in range(per):
        r=call(dict(model=MODEL,max_tokens=3000,temperature=1.0,reasoning_effort="medium",
                    seed=5000+tot,messages=[{"role":"user","content":prompt}],
                    tools=TOOLS,tool_choice="auto"))
        tot+=1; status="?"
        if not r["ok"]: status=r["err"]
        else:
            tc=r["tc"]
            if not tc: status="no tool_call (text %d chars)"%len(r["content"])
            else:
                try:
                    args=json.loads(tc[0]["function"]["arguments"])
                    if "path" not in args or "content" not in args: status="missing fields"
                    else:
                        good,msg=chk(args["content"]); status="PASS" if good else msg
                except Exception as e: status="args not JSON: %s"%str(e)[:38]
        p=(status=="PASS"); v+=p; okn+=p
        if not p: fails.append((name,i,status))
        print("%-13s s%d %s"%(name,i,"PASS" if p else "FAIL "+status),flush=True)
    res[name]="%d/%d"%(v,per)
print("\nRESULT %s total=%d/%d target=%s"%(json.dumps(res),okn,tot,URL))
for f in fails[:8]: print("  fail:",f)
print("TOOLAB_DONE")
