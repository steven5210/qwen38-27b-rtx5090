#!/usr/bin/env python3
"""Qwen local MCP 1.3.0, for macOS and Linux/WSL (Python standard library only).

Jobs share durable JSON records, crash-released ownership leases and one generation
lock across MCP processes using the same jobs directory. Direct Qwen Code clients
are scheduled by NINFER separately. Existing completed v1.2 records remain readable.
No model, reasoning-effort, output-budget or inference-server settings are changed.
"""
import contextlib
import fcntl
import json
import math
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

VERSION = "1.3.0"
BASE = os.environ.get("QWEN_URL", "http://127.0.0.1:8080").rstrip("/")
D = os.path.dirname(os.path.abspath(__file__))
try:
    with open(os.path.join(D, "api-key.txt")) as f:
        KEY = f.read().strip()
except OSError:
    KEY = ""
WINDOW = 262_144
MAX_SYNC_TOKENS = 4096
MAX_PAYLOAD_BYTES = 2_000_000
WAIT_DEFAULT_S = 45.0
WAIT_MAX_S = 50.0
POLL_S = 0.2
SNAPSHOT_S = 1.0
KEEP_RESULTS = 50
LIVE_STATES = ("queued", "running")
TERMINAL_STATES = ("done", "error", "incomplete", "cancelled")
JOBS_DIR = os.path.join(D, "jobs")
REGISTRY_LOCK = threading.RLock()
OUT_LOCK = threading.Lock()
ACTIVE = threading.Semaphore(1)
OWNER = uuid.uuid4().hex
OWNERS = {}


class ToolError(Exception):
    """A user-visible failed or incomplete operation, including any partial output."""


@contextlib.contextmanager
def registry():
    # Separate opens alone do not replace a thread lock on every supported OS.
    with REGISTRY_LOCK:
        os.makedirs(JOBS_DIR, exist_ok=True)
        with open(os.path.join(JOBS_DIR, ".registry.lock"), "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def validate_jid(jid):
    if not isinstance(jid, str) or not re.fullmatch(r"[0-9a-f]{8,32}", jid):
        raise ToolError("Invalid job_id; use the ID returned by qwen_submit.")
    return jid


def record_path(jid):
    return os.path.join(JOBS_DIR, validate_jid(jid) + ".json")


def ensure_owner(owner=OWNER):
    # Called under registry(). A held file lock is the lease, not PID existence.
    if owner not in OWNERS:
        handle = open(os.path.join(JOBS_DIR, ".owner-" + owner + ".lock"), "a+b")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            handle.close()
            raise
        OWNERS[owner] = handle


def release_owner(owner):
    # Release even if final persistence failed: a reader can then report an
    # interrupted job instead of waiting forever on a healthy but idle process.
    with REGISTRY_LOCK:
        handle = OWNERS.pop(owner, None)
        if handle is not None:
            handle.close()
            try:
                os.unlink(os.path.join(JOBS_DIR, ".owner-" + owner + ".lock"))
            except OSError:
                pass


def owner_alive(owner):
    if not isinstance(owner, str) or not re.fullmatch(r"[0-9a-f]{32}", owner):
        return False
    if owner in OWNERS:
        return True
    try:
        with open(os.path.join(JOBS_DIR, ".owner-" + owner + ".lock"), "r+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(lock, fcntl.LOCK_UN)
    except FileNotFoundError:
        pass
    return False


def read_record(jid):
    try:
        with open(record_path(jid), encoding="utf-8") as f:
            rec = json.load(f)
    except FileNotFoundError:
        return None
    if not isinstance(rec, dict):
        raise ToolError("Saved job %s is not a valid record." % jid)
    return rec


def write_record(jid, rec):
    # Caller holds registry(). A unique temporary file also avoids v1.2 temp names.
    fd, tmp = tempfile.mkstemp(prefix="." + jid + "-", suffix=".tmp", dir=JOBS_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, record_path(jid))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def recover_record(jid, rec):
    if rec.get("state") in LIVE_STATES and not owner_alive(rec.get("owner")):
        rec["state"] = "incomplete" if rec.get("answer") or rec.get("thinking_chars") else "error"
        rec["ended"] = time.time()
        rec["error"] = "Interrupted: the owning MCP process exited. Partial output is not a completed result; resubmit deliberately."
        if not rec.get("owner"):
            rec["error"] = ("Legacy v1.2 job has no recoverable owner. After a full Claude restart, "
                            "resubmit it. If an old v1.2 process is still running, check that process first.")
        write_record(jid, rec)
    return rec


def all_records(recover=False):
    records = {}
    for name in os.listdir(JOBS_DIR):
        if not re.fullmatch(r"[0-9a-f]{8,32}\.json", name):
            continue
        jid = name[:-5]
        try:
            rec = read_record(jid)
            if rec is not None:
                records[jid] = recover_record(jid, rec) if recover else rec
        except (ValueError, ToolError):
            # Do not delete a malformed record or let it hide otherwise valid jobs.
            continue
    return records


def completion_time(jid, rec):
    value = rec.get("ended")
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    return os.path.getmtime(record_path(jid))


def prune_records():
    # Retain every live record and the newest 50 terminal records, by completion.
    records = all_records()
    terminal = [(completion_time(jid, rec), jid) for jid, rec in records.items()
                if rec.get("state") in TERMINAL_STATES]
    terminal.sort()
    for _, jid in terminal[:-KEEP_RESULTS]:
        os.unlink(record_path(jid))


def persist(jid, rec, terminal=False):
    with registry():
        write_record(jid, rec)
        if terminal:
            prune_records()


def get_job(jid):
    validate_jid(jid)
    with registry():
        rec = read_record(jid)
        if rec is None:
            raise ToolError("Unknown or expired job_id: %s. The newest %d completed results are retained." % (jid, KEEP_RESULTS))
        return recover_record(jid, rec)


def http(path, body=None, timeout=8):
    headers = {"Authorization": "Bearer " + KEY}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    return urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=headers), timeout=timeout)


def est_tokens(s):
    return int(len(s) / 3.5) + 16


def sse_data(response):
    parts = []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if parts:
                yield "\n".join(parts)
                parts = []
        elif line.startswith("data:"):
            value = line[5:]
            parts.append(value[1:] if value.startswith(" ") else value)
        # Comments, event names, IDs and retry hints do not carry model output.
    # An event without its blank-line terminator is incomplete SSE, not success.
    if parts:
        raise ToolError("Interrupted SSE event at end of stream.")


def error_message(exc):
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = exc.read(4096).decode("utf-8", "replace")
        except Exception:
            detail = ""
        return "HTTP %s: %s" % (exc.code, detail or exc.reason)
    return "%s: %s" % (type(exc).__name__, exc)


def consume_stream(response, rec, checkpoint):
    saw_done = False
    saw_tools = False
    for payload in sse_data(response):
        if payload == "[DONE]":
            saw_done = True
            break
        chunk = json.loads(payload)  # Malformed frames are failures, never skipped.
        if not isinstance(chunk, dict):
            raise ToolError("Malformed SSE JSON: expected an object.")
        if "error" in chunk:
            raise ToolError("NINFER stream error: " + json.dumps(chunk["error"], ensure_ascii=False))
        if chunk.get("usage"):
            rec["usage"] = chunk["usage"]
        for choice in chunk.get("choices", []):
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content"):
                rec["thinking_chars"] += len(delta["reasoning_content"])
                rec["phase"] = "thinking"
            if delta.get("content"):
                rec["answer"] += delta["content"]
                rec["phase"] = "answering"
            if delta.get("tool_calls"):
                saw_tools = True
            if choice.get("finish_reason"):
                rec["finish"] = choice["finish_reason"]
        checkpoint()
    if not saw_done:
        raise ToolError("Interrupted stream: missing terminal [DONE].")
    if not rec.get("finish"):
        raise ToolError("Interrupted stream: missing finish_reason.")
    if rec["finish"] == "length":
        rec["state"] = "incomplete"
        rec["error"] = "Output/context limit reached. The answer may be truncated; this job is not complete."
    elif rec["finish"] != "stop" or saw_tools:
        rec["state"] = "incomplete"
        rec["error"] = "Unexpected finish/tool output (%s). This text-only MCP does not execute tools." % rec["finish"]
    else:
        rec["state"] = "done"


def run_job(jid, body, rec):
    try:
        # flock is released by the OS even if Claude terminates this process.
        with ACTIVE:
            with open(os.path.join(JOBS_DIR, ".generation.lock"), "a+b") as slot:
                fcntl.flock(slot, fcntl.LOCK_EX)
                rec["state"] = "running"
                rec["phase"] = "connecting"
                persist(jid, rec)
                last_saved = time.monotonic()

                def checkpoint():
                    nonlocal last_saved
                    if time.monotonic() - last_saved >= SNAPSHOT_S:
                        persist(jid, rec)
                        last_saved = time.monotonic()

                try:
                    with http("/v1/chat/completions", body, timeout=3900) as response:
                        consume_stream(response, rec, checkpoint)
                finally:
                    fcntl.flock(slot, fcntl.LOCK_UN)
    except Exception as exc:
        rec["state"] = "incomplete" if rec.get("answer") or rec.get("thinking_chars") else "error"
        rec["error"] = error_message(exc)
    rec["ended"] = time.time()
    try:
        persist(jid, rec, terminal=True)
    except Exception as exc:
        # Fail visibly instead of silently claiming the result was saved.
        sys.stderr.write("qwen-local: could not persist terminal job %s: %s\n" % (jid, error_message(exc)))
        sys.stderr.flush()
    finally:
        release_owner(rec.get("owner"))


def start_job(task, body, effort):
    jid = uuid.uuid4().hex
    with registry():
        ensure_owner(jid)
        rec = {"state": "queued", "started": time.time(), "ended": None,
               "phase": "queued", "task_preview": task[:120], "answer": "",
               "thinking_chars": 0, "usage": None, "error": None, "finish": None,
               "effort": effort, "owner": jid, "owner_pid": os.getpid(),
               "bridge_version": VERSION}
        try:
            write_record(jid, rec)
        except BaseException:
            release_owner(jid)
            raise
    try:
        threading.Thread(target=run_job, args=(jid, body, rec), daemon=True).start()
    except Exception as exc:
        rec.update(state="error", ended=time.time(), error=error_message(exc))
        try:
            persist(jid, rec, terminal=True)
        finally:
            release_owner(jid)
        raise
    return jid


def wait_job(jid, seconds):
    end = time.monotonic() + seconds
    while True:
        rec = get_job(jid)
        remaining = end - time.monotonic()
        if rec["state"] not in LIVE_STATES or remaining <= 0:
            return rec
        time.sleep(min(POLL_S, remaining))


def t_health(args):
    with http("/health", timeout=4) as r:
        health = json.load(r)
    if health.get("status") != "ok":
        raise ToolError("NINFER is not ready: %s" % health)
    with http("/v1/models", timeout=4) as r:
        model = json.load(r)["data"][0]
    with registry():
        jobs = {jid: rec.get("state") for jid, rec in all_records(recover=True).items()}
    window = model.get("max_model_len", WINDOW)
    source = "server-reported" if "max_model_len" in model else "configured fallback"
    return ("UP -- model %s at %s, window %s tokens (%s), qwen-local v%s. "
            "MCP generations: 1 shared slot on this host. Jobs: %s" %
            (model["id"], BASE, format(window, ","), source, VERSION, jobs or "none"))


def nonempty_text(args, key):
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError("%s must be a nonempty string." % key)
    return value


def check_payload(body):
    size = len(json.dumps(body).encode())
    if size > MAX_PAYLOAD_BYTES:
        raise ToolError("Request body is %s bytes; limit %s. Trim context." % (size, MAX_PAYLOAD_BYTES))
    return size


def t_ask(args):
    question = nonempty_text(args, "question")
    effort = args.get("effort", "low")
    if effort not in ("none", "low"):
        raise ToolError("effort for qwen_ask must be none|low; use qwen_submit for bigger tasks.")
    body = {"model": "qwen3.8-27b", "max_tokens": MAX_SYNC_TOKENS,
            "reasoning_effort": effort, "messages": [{"role": "user", "content": question}],
            "stream": True, "stream_options": {"include_usage": True}}
    check_payload(body)
    jid = start_job(question, body, effort)
    rec = wait_job(jid, min(WAIT_DEFAULT_S, WAIT_MAX_S))
    if rec["state"] in LIVE_STATES:
        return ("Job %s is still %s; the quick-call wait ended cleanly. Do not resubmit. "
                "Use qwen_status with wait:true, then qwen_result." % (jid, rec["state"]))
    return render_result(jid, rec)


def t_submit(args):
    task = nonempty_text(args, "task")
    context = args.get("context", "")
    system = args.get("system", "")
    if not isinstance(context, str) or not isinstance(system, str):
        raise ToolError("context and system must be strings.")
    effort = args.get("effort", "xhigh")
    if effort not in ("none", "low", "medium", "xhigh"):
        raise ToolError("effort must be none|low|medium|xhigh.")
    max_tokens = args.get("max_tokens", 131_072)
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 0 < max_tokens < WINDOW:
        raise ToolError("max_tokens must be a positive integer smaller than the context window.")
    path = args.get("context_path")
    if path:
        if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path):
            raise ToolError("context_path must name an existing absolute file path.")
        with open(path, "rb") as f:
            data = f.read(MAX_PAYLOAD_BYTES + 1)
        if len(data) > MAX_PAYLOAD_BYTES:
            raise ToolError("context_path exceeds the 2,000,000-byte limit; trim the file.")
        context += ("\n\n" if context else "") + data.decode("utf-8", "replace")
    content = task + ("\n\n--- CONTEXT ---\n" + context if context else "")
    needed = est_tokens(content) + est_tokens(system)
    if needed > WINDOW - max_tokens:
        raise ToolError("Estimated prompt %s exceeds the %s tokens available beside max_tokens=%s. Trim context." %
                        (needed, WINDOW - max_tokens, max_tokens))
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
    body = {"model": "qwen3.8-27b", "max_tokens": max_tokens, "reasoning_effort": effort,
            "stream": True, "stream_options": {"include_usage": True}, "messages": messages}
    size = check_payload(body)
    jid = start_job(task, body, effort)
    return ("Job %s submitted (effort=%s, max_tokens=%s, prompt ~%s tokens, body %s bytes). "
            "One MCP generation runs at a time across processes on this host. "
            "Use qwen_status with wait:true; chain waits for long jobs." %
            (jid, effort, format(max_tokens, ","), format(needed, ","), format(size, ",")))


def t_status(args):
    jid = validate_jid(args.get("job_id"))
    started = time.monotonic()
    if args.get("wait"):
        try:
            seconds = float(args.get("timeout_s", WAIT_DEFAULT_S))
            if not math.isfinite(seconds):
                seconds = WAIT_DEFAULT_S
        except (TypeError, ValueError):
            seconds = WAIT_DEFAULT_S
        rec = wait_job(jid, max(0.0, min(seconds, WAIT_MAX_S)))
    else:
        rec = get_job(jid)
    payload = {"job_id": jid, "state": rec["state"], "phase": rec.get("phase"),
               "elapsed_s": round((rec.get("ended") or time.time()) - rec["started"], 1),
               "thinking_chars": rec.get("thinking_chars", 0), "answer_chars": len(rec.get("answer", "")),
               "finish": rec.get("finish"), "error": rec.get("error"), "task": rec.get("task_preview", "")}
    if args.get("wait"):
        payload["waited_s"] = round(time.monotonic() - started, 1)
        if rec["state"] in LIVE_STATES:
            payload["note"] = "Still running/queued; call qwen_status wait:true again. Do not resubmit."
    text = json.dumps(payload)
    if rec["state"] in ("error", "incomplete", "cancelled"):
        raise ToolError(text)
    return text


def render_result(jid, rec):
    if rec["state"] in LIVE_STATES:
        return "Job %s is %s. Use qwen_status wait:true, then qwen_result." % (jid, rec["state"])
    usage = rec.get("usage") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    meta = "\n\n[job=%s | state=%s | finish=%s | prompt=%s (cached %s) | output=%s | %.0fs]" % (
        jid, rec["state"], rec.get("finish"), usage.get("prompt_tokens"), cached,
        usage.get("completion_tokens"), (rec.get("ended") or time.time()) - rec["started"])
    text = (rec.get("answer") or "") + meta
    if rec["state"] != "done":
        raise ToolError("JOB %s: %s\n\nPARTIAL OUTPUT (not a completed result):\n%s" %
                        (rec["state"].upper(), rec.get("error") or "No completion confirmation", text))
    return text


def t_result(args):
    jid = validate_jid(args.get("job_id"))
    rec = get_job(jid)
    text = render_result(jid, rec)
    if args.get("include_thinking"):
        text += " [thinking omitted: %d chars streamed]" % rec.get("thinking_chars", 0)
    return text


TOOLS = [
 dict(name="qwen_health", description="Check the local Qwen3.8-27B server (ninfer :8080): up/down, model, window, running jobs.",
      inputSchema={"type": "object", "properties": {}, "required": []}),
 dict(name="qwen_ask", description="Quick question to local Qwen (effort none|low, <=4K output). Shares the one-job queue; returns a job_id if not finished within 45 seconds. Do not resubmit; use qwen_status/qwen_result. For implementation tasks use qwen_submit.",
      inputSchema={"type": "object", "properties": {"question": {"type": "string"}, "effort": {"type": "string", "enum": ["none", "low"]}}, "required": ["question"]}),
 dict(name="qwen_submit", description="Delegate a bounded task (coding implementation, refactor, tests, summarization) to local Qwen as a background job at reasoning_effort xhigh by default. Write a SELF-CONTAINED spec: goal, constraints, interfaces; put needed file contents in context, or point context_path at a local file the MCP will read and inline (<=2MB; avoids pasting huge strings through tool parameters). Returns a job_id immediately. Then chain qwen_status wait:true calls until completion -- no polling loops.",
      inputSchema={"type": "object", "properties": {
          "task": {"type": "string", "description": "the complete self-contained spec"},
          "context": {"type": "string", "description": "file contents / code the task needs (inline)"},
          "context_path": {"type": "string", "description": "absolute path to a local file; the MCP server reads it and appends it to context before forwarding. Max 2,000,000 bytes."},
          "system": {"type": "string"},
          "effort": {"type": "string", "enum": ["none", "low", "medium", "xhigh"]},
          "max_tokens": {"type": "integer", "description": "output budget, default 131072 (thinking+answer)"}},
          "required": ["task"]}),
 dict(name="qwen_status", description="Progress of a qwen_submit job. Default: instant snapshot (state, phase thinking/answering, elapsed, sizes). With wait:true it BLOCKS until the job reaches done/error/incomplete or timeout_s elapses (default 45, hard-clamped to 50 so the MCP harness never kills the server process), then returns the same payload -- a clean 'still running' note at the clamp, never an error. For multi-minute jobs CHAIN wait calls back-to-back: each is one turn, waking fires within ~1s of actual completion, no sleep-timer math needed. Other tool calls are not blocked while waiting. Jobs are shared across local MCP processes. The newest 50 terminal results persist across restarts; incomplete/failed jobs are reported as errors.",
      inputSchema={"type": "object", "properties": {"job_id": {"type": "string"},
          "wait": {"type": "boolean", "description": "block until done/error or timeout_s"},
          "timeout_s": {"type": "number", "description": "max seconds to block (default 45, clamped to 50 -- chain calls for longer jobs)"}},
          "required": ["job_id"]}),
 dict(name="qwen_result", description="Fetch the finished answer of a qwen_submit job (with usage stats; thinking not returned). Served from the persisted registry, so results survive MCP restarts.",
      inputSchema={"type": "object", "properties": {"job_id": {"type": "string"}, "include_thinking": {"type": "boolean"}}, "required": ["job_id"]}),
]
HANDLERS = {"qwen_health": t_health, "qwen_ask": t_ask, "qwen_submit": t_submit,
            "qwen_status": t_status, "qwen_result": t_result}


def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error:
        msg["error"] = {"code": -32000, "message": error}
    else:
        msg["result"] = result
    with OUT_LOCK:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def handle_call(mid, name, args):
    if not isinstance(name, str):
        reply(mid, error="tool name must be a string")
        return
    fn = HANDLERS.get(name)
    if fn is None:
        reply(mid, error="unknown tool " + str(name))
        return
    failed = False
    try:
        if not isinstance(args, dict):
            raise ToolError("Tool arguments must be an object.")
        text = fn(args)
    except Exception as exc:
        failed = True
        text = str(exc) if isinstance(exc, ToolError) else error_message(exc)
    reply(mid, {"content": [{"type": "text", "text": text}], "isError": failed})


def main():
    for raw in sys.stdin:
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                continue
        except ValueError:
            continue
        method, mid = message.get("method"), message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            if mid is not None:
                reply(mid, error="params must be an object")
            continue
        if method == "initialize":
            reply(mid, {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "qwen-local", "version": VERSION}})
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            reply(mid, {})
        elif method == "tools/list":
            reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            threading.Thread(target=handle_call,
                             args=(mid, params.get("name"), params.get("arguments", {})),
                             daemon=True).start()
        elif mid is not None:
            reply(mid, error="unsupported method " + str(method))


if __name__ == "__main__":
    main()
