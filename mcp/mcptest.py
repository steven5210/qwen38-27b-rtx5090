#!/usr/bin/env python3
"""Optional live stdio smoke check; sends short requests to the configured NINFER.

Use test_bridge.py for isolated regression tests without production inference.
Pass the deployed qwen_mcp.py path so its adjacent api-key.txt is available.
"""
import argparse
import json
from pathlib import Path
import re
import select
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bridge", nargs="?", type=Path,
                        default=Path(__file__).with_name("qwen_mcp.py"))
    args = parser.parse_args()
    process = subprocess.Popen([sys.executable, "-u", "-B", str(args.bridge.resolve())],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, bufsize=1)
    request_id = 0

    def rpc(method, params=None):
        nonlocal request_id
        request_id += 1
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id,
                                       "method": method, "params": params or {}}) + "\n")
        process.stdin.flush()
        if not select.select([process.stdout], [], [], 55)[0]:
            raise RuntimeError("MCP response timeout for " + method)
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("MCP process exited before replying")
        response = json.loads(line)
        if response.get("id") != request_id or "error" in response:
            raise RuntimeError("MCP protocol error: " + json.dumps(response))
        return response["result"]

    def call(name, arguments=None):
        result = rpc("tools/call", {"name": name, "arguments": arguments or {}})
        text = "\n".join(part.get("text", "") for part in result.get("content", [])
                         if part.get("type") == "text")
        print("== %s -> %s" % (name, text[:300].replace("\n", " | ")))
        if result.get("isError"):
            raise RuntimeError(name + " failed: " + text)
        return text

    def finish_job(jid):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            status = json.loads(call("qwen_status", {
                "job_id": jid, "wait": True,
                "timeout_s": min(45, max(0, deadline - time.monotonic()))}))
            if status["state"] == "done":
                return call("qwen_result", {"job_id": jid})
            if status["state"] not in ("queued", "running"):
                raise RuntimeError("Job did not complete: " + json.dumps(status))
        raise RuntimeError("Job %s did not finish within 300 seconds" % jid)

    try:
        initialized = rpc("initialize", {"protocolVersion": "2025-06-18",
                          "capabilities": {}, "clientInfo": {"name": "qwen-live-smoke", "version": "1"}})
        print("== initialize ->", json.dumps(initialized))
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        names = {tool["name"] for tool in rpc("tools/list")["tools"]}
        expected = {"qwen_health", "qwen_ask", "qwen_submit", "qwen_status", "qwen_result"}
        if not expected.issubset(names):
            raise RuntimeError("Required tools missing: " + str(expected - names))
        call("qwen_health")
        quick = call("qwen_ask", {"question": "Reply with exactly: DELEGATION-OK", "effort": "none"})
        pending = re.match(r"Job ([0-9a-f]+) is still (?:queued|running)", quick)
        if pending:
            quick = finish_job(pending.group(1))
        if "DELEGATION-OK" not in quick:
            raise RuntimeError("Quick response did not contain the requested marker")
        submitted = call("qwen_submit", {
            "task": "Write a Python one-liner that reverses a string. Reply with just the code.",
            "effort": "low", "max_tokens": 2048})
        match = re.match(r"Job ([0-9a-f]+) submitted", submitted)
        if not match:
            raise RuntimeError("Submission did not return a job ID")
        finish_job(match.group(1))
        print("MCPTEST_DONE")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


if __name__ == "__main__":
    main()
