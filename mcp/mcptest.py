#!/usr/bin/env python3
"""Drive qwen_mcp.py over stdio exactly like Claude Desktop would."""
import json, subprocess, sys, time
P = subprocess.Popen(["python3", "-u", "/mnt/c/Users/StevenPC/Downloads/qwen38/qwen_mcp.py"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
def send(m): P.stdin.write(json.dumps(m) + "\n"); P.stdin.flush()
def recv(timeout=95):
    import select
    r, _, _ = select.select([P.stdout], [], [], timeout)
    return json.loads(P.stdout.readline()) if r else {"TIMEOUT": True}
def call(i, name, args):
    send({"jsonrpc": "2.0", "id": i, "method": "tools/call",
          "params": {"name": name, "arguments": args}})
    r = recv()
    txt = r.get("result", {}).get("content", [{}])[0].get("text", r)
    print("== %s ->" % name, str(txt)[:300].replace("\n", " | "))
    return txt

send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}})
print("== initialize ->", json.dumps(recv())[:160])
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
print("== tools/list ->", [t["name"] for t in recv()["result"]["tools"]])
call(3, "qwen_health", {})
call(4, "qwen_ask", {"question": "Reply with exactly: DELEGATION-OK", "effort": "none"})
sub = call(5, "qwen_submit", {"task": "Write a python one-liner that reverses a string. Reply with just the code.",
                              "effort": "low", "max_tokens": 2048})
jid = sub.split("Job ")[1].split(" ")[0] if "Job " in sub else None
print("== job id:", jid)
for _ in range(20):
    time.sleep(3)
    st = call(6, "qwen_status", {"job_id": jid})
    if '"done"' in st or '"error"' in st: break
call(7, "qwen_result", {"job_id": jid})
P.terminate()
print("MCPTEST_DONE")
