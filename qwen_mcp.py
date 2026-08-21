#!/usr/bin/env python3
"""qwen_mcp.py -- local MCP server that lets Claude delegate work to the Qwen3.8-27B
ninfer server on this machine. Zero dependencies; runs inside WSL (launched by Claude
Desktop via wsl.exe) so it reaches 127.0.0.1:8080 directly.

Tools:
  qwen_health()                     -- is the server up, which model/window
  qwen_ask(question, effort=low)    -- synchronous quick lane (keep under ~45s: none/low)
  qwen_submit(task, context?, ...)  -- start a big job (default effort xhigh), returns job_id
  qwen_status(job_id)               -- phase (thinking/answering), elapsed, sizes
  qwen_result(job_id)               -- the answer (+usage; thinking omitted by default)

Timeout-proof by design: submit returns instantly; each poll returns instantly; the
generation itself can run for many minutes on the server unaffected."""
import json, os, sys, threading, time, urllib.request, urllib.error, uuid

BASE = os.environ.get("QWEN_URL", "http://127.0.0.1:8080")
D = os.path.dirname(os.path.abspath(__file__))
try: KEY = open(os.path.join(D, "api-key.txt")).read().strip()
except Exception: KEY = ""
WINDOW = 252_928
MAX_SYNC_TOKENS = 4096
JOBS = {}
LOCK = threading.Lock()
ACTIVE = threading.Semaphore(int(os.environ.get("QWEN_MCP_JOBS", "1")))  # be gentle to live Cline sessions

def http(path, body=None, timeout=8, stream=False):
    headers = {"Authorization": "Bearer " + KEY}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)

def est_tokens(s): return int(len(s) / 3.5) + 16

def run_job(jid, body):
    with ACTIVE:
        j = JOBS[jid]
        j["state"] = "running"
        try:
            body["stream"] = True
            with http("/v1/chat/completions", body, timeout=3900) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data: "): continue
                    payload = line[6:]
                    if payload == "[DONE]": break
                    try: ch = json.loads(payload)
                    except ValueError: continue
                    if ch.get("usage"): j["usage"] = ch["usage"]
                    for c in ch.get("choices", []):
                        d = c.get("delta", {})
                        if d.get("reasoning_content"):
                            j["thinking_chars"] += len(d["reasoning_content"]); j["phase"] = "thinking"
                        if d.get("content"):
                            j["answer"] += d["content"]; j["phase"] = "answering"
                        if d.get("tool_calls"): j["phase"] = "tool_call?"
                        if c.get("finish_reason"): j["finish"] = c["finish_reason"]
            j["state"] = "done"
        except Exception as e:
            j["state"] = "error"; j["error"] = "%s: %s" % (type(e).__name__, e)
        j["ended"] = time.time()

def t_health(args):
    try:
        m = json.loads(http("/v1/models", timeout=4).read().decode())
        return ("UP -- model %s at %s, window %s tokens. Jobs: %s" %
                (m["data"][0]["id"], BASE, format(WINDOW, ","),
                 {k: v["state"] for k, v in JOBS.items()} or "none"))
    except Exception as e:
        return ("DOWN (%s). Ask the user to run START-NINFER.bat -- the server boots in ~10s." % e)

def t_ask(args):
    q = args["question"]; eff = args.get("effort", "low")
    if eff not in ("none", "low"): return "effort for qwen_ask must be none|low (use qwen_submit for bigger)."
    body = {"model": "qwen3.8-27b", "max_tokens": MAX_SYNC_TOKENS, "reasoning_effort": eff,
            "messages": [{"role": "user", "content": q}]}
    try:
        r = json.loads(http("/v1/chat/completions", body, timeout=90).read().decode())
        msg = r["choices"][0]["message"]
        u = r.get("usage", {})
        return (msg.get("content") or "") + "\n\n[usage: prompt %s, output %s, finish %s]" % (
            u.get("prompt_tokens"), u.get("completion_tokens"), r["choices"][0].get("finish_reason"))
    except Exception as e:
        return "qwen_ask failed: %s -- if the server is down, ask the user to run START-NINFER.bat" % e

def t_submit(args):
    task = args["task"]; ctx = args.get("context", "")
    eff = args.get("effort", "xhigh"); maxtok = int(args.get("max_tokens", 131_072))
    system = args.get("system", "")
    content = task + (("\n\n--- CONTEXT ---\n" + ctx) if ctx else "")
    budget = WINDOW - maxtok
    need = est_tokens(content) + est_tokens(system)
    if need > budget:
        return ("REJECTED before sending: prompt ~%s tokens but only %s fit beside max_tokens=%s "
                "(window %s). Trim context or lower max_tokens." %
                (format(need, ","), format(budget, ","), format(maxtok, ","), format(WINDOW, ",")))
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
    body = {"model": "qwen3.8-27b", "max_tokens": maxtok, "reasoning_effort": eff,
            "stream_options": {"include_usage": True}, "messages": msgs}
    jid = uuid.uuid4().hex[:8]
    with LOCK:
        JOBS[jid] = {"state": "queued", "started": time.time(), "ended": None, "phase": "queued",
                     "task_preview": task[:120], "answer": "", "thinking_chars": 0,
                     "usage": None, "error": None, "finish": None, "effort": eff}
    threading.Thread(target=run_job, args=(jid, body), daemon=True).start()
    return ("Job %s submitted (effort=%s, max_tokens=%s, prompt ~%s tokens). "
            "Poll with qwen_status; typical xhigh jobs think for 2-10 minutes." %
            (jid, eff, format(maxtok, ","), format(need, ",")))

def t_status(args):
    j = JOBS.get(args["job_id"])
    if not j: return "unknown job_id. Known: %s" % list(JOBS)
    el = (j["ended"] or time.time()) - j["started"]
    return json.dumps({"state": j["state"], "phase": j["phase"], "elapsed_s": round(el, 1),
                       "thinking_chars": j["thinking_chars"], "answer_chars": len(j["answer"]),
                       "finish": j["finish"], "error": j["error"], "task": j["task_preview"]})

def t_result(args):
    j = JOBS.get(args["job_id"])
    if not j: return "unknown job_id. Known: %s" % list(JOBS)
    if j["state"] in ("queued", "running"):
        return "not finished (state=%s, phase=%s). Poll qwen_status and try again." % (j["state"], j["phase"])
    if j["state"] == "error": return "job failed: %s" % j["error"]
    out = j["answer"]
    u = j["usage"] or {}
    ptd = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
    meta = "\n\n[finish=%s | prompt=%s (cached %s) | output=%s | %.0fs]" % (
        j["finish"], u.get("prompt_tokens"), ptd, u.get("completion_tokens"),
        (j["ended"] or time.time()) - j["started"])
    if args.get("include_thinking"): meta += " [thinking omitted: %d chars streamed]" % j["thinking_chars"]
    return out + meta

TOOLS = [
 dict(name="qwen_health", description="Check the local Qwen3.8-27B server (ninfer :8080): up/down, model, window, running jobs.",
      inputSchema={"type": "object", "properties": {}, "required": []}),
 dict(name="qwen_ask", description="Quick synchronous question to local Qwen (effort none|low, <=4K output, seconds). For implementation tasks use qwen_submit.",
      inputSchema={"type": "object", "properties": {"question": {"type": "string"}, "effort": {"type": "string", "enum": ["none", "low"]}}, "required": ["question"]}),
 dict(name="qwen_submit", description="Delegate a bounded task (coding implementation, refactor, tests, summarization) to local Qwen as a background job at reasoning_effort xhigh by default. Write a SELF-CONTAINED spec: goal, constraints, interfaces, and paste needed file contents into context. Returns a job_id immediately -- no timeout risk. Poll qwen_status, fetch qwen_result.",
      inputSchema={"type": "object", "properties": {
          "task": {"type": "string", "description": "the complete self-contained spec"},
          "context": {"type": "string", "description": "file contents / code the task needs"},
          "system": {"type": "string"},
          "effort": {"type": "string", "enum": ["none", "low", "medium", "xhigh"]},
          "max_tokens": {"type": "integer", "description": "output budget, default 131072 (thinking+answer)"}},
          "required": ["task"]}),
 dict(name="qwen_status", description="Progress of a qwen_submit job: state, phase (thinking/answering), elapsed seconds, sizes.",
      inputSchema={"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}),
 dict(name="qwen_result", description="Fetch the finished answer of a qwen_submit job (with usage stats; thinking not returned).",
      inputSchema={"type": "object", "properties": {"job_id": {"type": "string"}, "include_thinking": {"type": "boolean"}}, "required": ["job_id"]}),
]
HANDLERS = {"qwen_health": t_health, "qwen_ask": t_ask, "qwen_submit": t_submit,
            "qwen_status": t_status, "qwen_result": t_result}

def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error: msg["error"] = {"code": -32000, "message": error}
    else: msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n"); sys.stdout.flush()

def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw: continue
        try: m = json.loads(raw)
        except ValueError: continue
        meth, mid = m.get("method"), m.get("id")
        if meth == "initialize":
            reply(mid, {"protocolVersion": m["params"].get("protocolVersion", "2025-06-18"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "qwen-local", "version": "1.0.0"}})
        elif meth == "notifications/initialized": continue
        elif meth == "ping": reply(mid, {})
        elif meth == "tools/list": reply(mid, {"tools": TOOLS})
        elif meth == "tools/call":
            name = m["params"]["name"]; args = m["params"].get("arguments") or {}
            fn = HANDLERS.get(name)
            if not fn: reply(mid, error="unknown tool " + name); continue
            try: text = fn(args)
            except Exception as e: text = "%s failed: %s" % (name, e)
            reply(mid, {"content": [{"type": "text", "text": text}], "isError": False})
        elif mid is not None:
            reply(mid, error="unsupported method " + str(meth))

if __name__ == "__main__":
    main()
