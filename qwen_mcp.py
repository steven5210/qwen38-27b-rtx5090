#!/usr/bin/env python3
"""qwen_mcp.py -- local MCP server that lets Claude delegate work to the Qwen3.8-27B
ninfer server on this machine. Zero dependencies; runs inside WSL on the PC (launched by
Claude Desktop via wsl.exe) or natively on macOS (python3), reaching the server over
loopback or Tailscale via QWEN_URL.

Tools:
  qwen_health()                     -- is the server up, which model/window
  qwen_ask(question, effort=low)    -- synchronous quick lane (keep under ~45s: none/low)
  qwen_submit(task, context?, context_path?, ...) -- start a big job (default effort xhigh)
  qwen_status(job_id, wait?, timeout_s?) -- snapshot, or BLOCK until done/error/timeout
  qwen_result(job_id)               -- the answer (+usage; thinking omitted by default)

v1.1.0: qwen_status gains wait/timeout_s (completion push -- no polling loops);
qwen_submit gains context_path (MCP reads the file locally and inlines it) and a hard
2,000,000-byte payload cap with clear errors; tool calls now run on worker threads so a
blocking wait never stalls other tool calls."""
import json, os, sys, threading, time, urllib.request, urllib.error, uuid

BASE = os.environ.get("QWEN_URL", "http://127.0.0.1:8080")
D = os.path.dirname(os.path.abspath(__file__))
try: KEY = open(os.path.join(D, "api-key.txt")).read().strip()
except Exception: KEY = ""
WINDOW = 262_144
MAX_SYNC_TOKENS = 4096
MAX_PAYLOAD_BYTES = 2_000_000   # hard cap on one submit's JSON body (server: --max-request-mib 2)
WAIT_DEFAULT_S = 120.0
WAIT_MAX_S = 600.0
JOBS = {}
LOCK = threading.Lock()
OUT_LOCK = threading.Lock()
ACTIVE = threading.Semaphore(int(os.environ.get("QWEN_MCP_JOBS", "1")))  # be gentle to live Cline sessions

def http(path, body=None, timeout=8):
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
        j["event"].set()   # completion push: wake any qwen_status wait instantly

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
    cp = args.get("context_path")
    if cp:
        if not os.path.isabs(cp):
            return "REJECTED: context_path must be an absolute path (got %r)." % cp
        if not os.path.isfile(cp):
            return "REJECTED: context_path does not exist or is not a file: %s" % cp
        sz = os.path.getsize(cp)
        if sz > MAX_PAYLOAD_BYTES:
            return ("REJECTED: context_path file is %s bytes; the limit is %s bytes (2MB). "
                    "Split the file or trim it." % (format(sz, ","), format(MAX_PAYLOAD_BYTES, ",")))
        try:
            file_ctx = open(cp, encoding="utf-8", errors="replace").read()
        except Exception as e:
            return "REJECTED: could not read context_path: %s: %s" % (type(e).__name__, e)
        ctx = (ctx + "\n\n" if ctx else "") + file_ctx
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
    body_bytes = len(json.dumps(body).encode())
    if body_bytes > MAX_PAYLOAD_BYTES:
        return ("REJECTED before sending: request body is %s bytes; the limit is %s bytes (2MB, "
                "matching the server's --max-request-mib 2). Trim context or use a smaller file." %
                (format(body_bytes, ","), format(MAX_PAYLOAD_BYTES, ",")))
    jid = uuid.uuid4().hex[:8]
    with LOCK:
        JOBS[jid] = {"state": "queued", "started": time.time(), "ended": None, "phase": "queued",
                     "task_preview": task[:120], "answer": "", "thinking_chars": 0,
                     "usage": None, "error": None, "finish": None, "effort": eff,
                     "event": threading.Event()}
    threading.Thread(target=run_job, args=(jid, body), daemon=True).start()
    return ("Job %s submitted (effort=%s, max_tokens=%s, prompt ~%s tokens, body %s bytes). "
            "Use qwen_status with wait:true to block until it finishes; typical xhigh jobs "
            "think for 2-10 minutes." %
            (jid, eff, format(maxtok, ","), format(need, ","), format(body_bytes, ",")))

def status_payload(j, waited=None):
    el = (j["ended"] or time.time()) - j["started"]
    out = {"state": j["state"], "phase": j["phase"], "elapsed_s": round(el, 1),
           "thinking_chars": j["thinking_chars"], "answer_chars": len(j["answer"]),
           "finish": j["finish"], "error": j["error"], "task": j["task_preview"]}
    if waited is not None:
        out["waited_s"] = round(waited, 1)
        if j["state"] in ("queued", "running"):
            out["note"] = "still running -- wait timed out cleanly; call qwen_status wait:true again"
    return json.dumps(out)

def t_status(args):
    j = JOBS.get(args["job_id"])
    if not j: return "unknown job_id. Known: %s" % list(JOBS)
    if args.get("wait") and j["state"] in ("queued", "running"):
        try: timeout = float(args.get("timeout_s", WAIT_DEFAULT_S))
        except (TypeError, ValueError): timeout = WAIT_DEFAULT_S
        timeout = max(1.0, min(timeout, WAIT_MAX_S))
        t0 = time.time()
        j["event"].wait(timeout)          # completion push: returns the instant the job ends
        return status_payload(j, waited=time.time() - t0)
    return status_payload(j)

def t_result(args):
    j = JOBS.get(args["job_id"])
    if not j: return "unknown job_id. Known: %s" % list(JOBS)
    if j["state"] in ("queued", "running"):
        return "not finished (state=%s, phase=%s). Use qwen_status with wait:true to block until done." % (j["state"], j["phase"])
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
 dict(name="qwen_submit", description="Delegate a bounded task (coding implementation, refactor, tests, summarization) to local Qwen as a background job at reasoning_effort xhigh by default. Write a SELF-CONTAINED spec: goal, constraints, interfaces; put needed file contents in context, or point context_path at a local file the MCP will read and inline (<=2MB; avoids pasting huge strings through tool parameters). Returns a job_id immediately. Then qwen_status with wait:true blocks until completion -- no polling loops.",
      inputSchema={"type": "object", "properties": {
          "task": {"type": "string", "description": "the complete self-contained spec"},
          "context": {"type": "string", "description": "file contents / code the task needs (inline)"},
          "context_path": {"type": "string", "description": "absolute path to a local file; the MCP server reads it and appends it to context before forwarding. Max 2,000,000 bytes."},
          "system": {"type": "string"},
          "effort": {"type": "string", "enum": ["none", "low", "medium", "xhigh"]},
          "max_tokens": {"type": "integer", "description": "output budget, default 131072 (thinking+answer)"}},
          "required": ["task"]}),
 dict(name="qwen_status", description="Progress of a qwen_submit job. Default: instant snapshot (state, phase thinking/answering, elapsed, sizes). With wait:true it BLOCKS until the job reaches done/error or timeout_s elapses (default 120, max 600), then returns the same payload -- a clean 'still running' note on timeout, never an error. Waking is push-based: it fires within ~1s of actual completion. Other tool calls are not blocked while waiting.",
      inputSchema={"type": "object", "properties": {"job_id": {"type": "string"},
          "wait": {"type": "boolean", "description": "block until done/error or timeout_s"},
          "timeout_s": {"type": "number", "description": "max seconds to block (default 120, max 600)"}},
          "required": ["job_id"]}),
 dict(name="qwen_result", description="Fetch the finished answer of a qwen_submit job (with usage stats; thinking not returned).",
      inputSchema={"type": "object", "properties": {"job_id": {"type": "string"}, "include_thinking": {"type": "boolean"}}, "required": ["job_id"]}),
]
HANDLERS = {"qwen_health": t_health, "qwen_ask": t_ask, "qwen_submit": t_submit,
            "qwen_status": t_status, "qwen_result": t_result}

def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error: msg["error"] = {"code": -32000, "message": error}
    else: msg["result"] = result
    with OUT_LOCK:
        sys.stdout.write(json.dumps(msg) + "\n"); sys.stdout.flush()

def handle_call(mid, name, args):
    fn = HANDLERS.get(name)
    if not fn:
        reply(mid, error="unknown tool " + name); return
    try: text = fn(args)
    except Exception as e: text = "%s failed: %s" % (name, e)
    reply(mid, {"content": [{"type": "text", "text": text}], "isError": False})

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
                        "serverInfo": {"name": "qwen-local", "version": "1.1.0"}})
        elif meth == "notifications/initialized": continue
        elif meth == "ping": reply(mid, {})
        elif meth == "tools/list": reply(mid, {"tools": TOOLS})
        elif meth == "tools/call":
            name = m["params"]["name"]; args = m["params"].get("arguments") or {}
            # worker thread per call: a blocking wait must never stall other tool calls
            threading.Thread(target=handle_call, args=(mid, name, args), daemon=True).start()
        elif mid is not None:
            reply(mid, error="unsupported method " + str(meth))

if __name__ == "__main__":
    main()
