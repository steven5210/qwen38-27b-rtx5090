#!/usr/bin/env python3
"""
cachehit-eval.py -- does the prefix-cache-HIT path degrade output quality?

Motivation: vLLM PR #47861 (unmerged draft as of 0.27.1) reports that MTP speculative
decoding + prefix caching on hybrid Mamba/GDN models mis-aligns cache-hit lengths between
the attention group and the mamba group, producing "tool-call leakage, recall failures and
degenerate generations ON CACHE-HIT PATHS". Our production config is exactly that stack.

Design: identical probe set run twice against an identical ~18K-token shared prefix.
  PASS 1 = cold  (server has never seen this prefix)
  PASS 2 = hot   (prefix is now cached -> the suspect code path)
Scores are compared pass-to-pass. /metrics is scraped between passes to PROVE the hot pass
actually hit the cache -- otherwise a clean result would be meaningless.

Read-only: changes no server setting.
"""
import json, os, re, sys, time, argparse, urllib.request, subprocess, tempfile, random

BASE = "http://127.0.0.1:8000"
KEY  = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api-key.txt")).read().strip()
MODEL = "qwen3.8-27b"

def post(path, payload, timeout=900):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def metrics():
    """Return dict of prefix-cache counters."""
    try:
        req = urllib.request.Request(BASE + "/metrics", headers={"Authorization": "Bearer " + KEY})
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode()
    except Exception as e:
        return {"_error": str(e)}
    out = {}
    for line in txt.splitlines():
        if line.startswith("#") or "prefix_cache" not in line:
            continue
        m = re.match(r"^(\S+?)(?:\{[^}]*\})?\s+([0-9.eE+-]+)$", line)
        if m:
            out[m.group(1)] = out.get(m.group(1), 0.0) + float(m.group(2))
    return out

# ---------------------------------------------------------------- shared prefix
NEEDLES = {
    "RETRY_BACKOFF_MS":  "2750",
    "SHARD_REPLICA_MIN": "7",
    "AUDIT_FLUSH_ROWS":  "18400",
}

def build_prefix(target_chars=52000):
    """Synthetic but realistic multi-module codebase with planted exact-match facts
    and two behavioural specs the code probes must obey."""
    rnd = random.Random(20260818)
    parts = []
    parts.append("""# ===== internal platform bundle: services/ =====
# Reviewer note: this bundle is the authoritative source for constants and specs.

## services/config/defaults.py
DEFAULT_TIMEOUT_S = 30
RETRY_BACKOFF_MS = %s          # exponential base, do not change without an RFC
MAX_INFLIGHT = 64
SHARD_REPLICA_MIN = %s         # below this the coordinator refuses writes
AUDIT_FLUSH_ROWS = %s          # rows buffered before an audit flush
""" % (NEEDLES["RETRY_BACKOFF_MS"], NEEDLES["SHARD_REPLICA_MIN"], NEEDLES["AUDIT_FLUSH_ROWS"]))

    parts.append('''
## services/spec/DURATION.md
`parse_duration(s: str) -> int` returns MILLISECONDS.
Grammar: one or more `<number><unit>` chunks, optionally separated by spaces.
Units: `ms`, `s`, `m`, `h`, `d`. Numbers may be decimal (e.g. `1.5h`).
House rules that differ from every other library (this is the part reviewers get wrong):
  R1. A leading `-` negates the WHOLE expression, not just the first chunk.
      `-1h30m` == -(1h + 30m) == -5400000
  R2. Chunks are summed, and repeated units are allowed: `1h 1h` == 7200000.
  R3. Fractional milliseconds round HALF UP to the nearest whole ms. `0.5ms` -> 1.
      `1.4ms` -> 1, `1.5ms` -> 2, `-1.5ms` -> -2 (magnitude rounds, then sign applies).
  R4. Empty string, or any chunk with an unknown unit, raises ValueError.
  R5. A bare number with no unit raises ValueError -- there is no default unit.
''')

    parts.append('''
## services/spec/ROUTES.md
`route_match(pattern: str, path: str) -> dict | None`
Returns a dict of captured params on match, or None. Both inputs are `/`-separated.
  R1. A literal segment must match exactly (case-sensitive).
  R2. `:name` captures exactly one segment into key `name`.
  R3. `*name` is a greedy tail capture: it takes ALL remaining segments, joined by `/`,
      and may match ZERO segments (capturing the empty string). Only legal as the LAST
      segment of the pattern.
  R4. Trailing slashes are insignificant on BOTH inputs: `/a/` == `/a`.
  R5. An empty pattern `/` matches only the empty path `/`, returning `{}`.
  R6. If a `:name` segment would capture an empty string, that is NOT a match.
''')

    parts.append('''
## services/tools/registry.json
{"name": "shard_rebalance",
 "description": "Rebalance shards across replicas.",
 "parameters": {"type": "object",
   "properties": {
     "shard_id": {"type": "string"},
     "target_replicas": {"type": "integer", "description": "must be >= SHARD_REPLICA_MIN"},
     "drain_first": {"type": "boolean"}},
   "required": ["shard_id", "target_replicas"]}}
''')

    # filler modules to reach the token target
    i = 0
    while sum(len(p) for p in parts) < target_chars:
        i += 1
        parts.append('''
## services/mod_%03d/handler.py
import logging
log = logging.getLogger("mod_%03d")

class Handler%03d:
    """Handles %s events for the %s subsystem."""
    def __init__(self, bus, clock, budget=%d):
        self.bus = bus; self.clock = clock; self.budget = budget
        self._seen = {}
    def on_event(self, ev):
        key = (ev.kind, ev.shard)
        if key in self._seen and self.clock.now() - self._seen[key] < %d:
            log.debug("suppressing duplicate %%s", key)
            return None
        self._seen[key] = self.clock.now()
        return self.bus.publish(ev.kind, {"shard": ev.shard, "seq": ev.seq + %d})
    def drain(self, limit=%d):
        out = []
        for k in sorted(self._seen):
            if len(out) >= limit: break
            out.append(k)
        return out
''' % (i, i, i, rnd.choice(["ingest","compaction","audit","replication","gc"]),
       rnd.choice(["storage","query","control-plane","metering"]),
       rnd.randint(10, 900), rnd.randint(50, 5000), rnd.randint(1, 9), rnd.randint(8, 128)))
    return "\n".join(parts)

PREFIX = build_prefix()

# ---------------------------------------------------------------- scoring helpers
def extract_code(text):
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return blocks[-1] if blocks else text

def run_tests(code, tests):
    """Execute model code + assertions in a subprocess. Return (passed, detail)."""
    src = code + "\n\n" + tests + "\nprint('ALLPASS')\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src); path = f.name
    try:
        r = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=25)
        ok = "ALLPASS" in r.stdout
        return ok, (r.stdout + r.stderr)[-300:]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    finally:
        try: os.unlink(path)
        except Exception: pass

def degeneracy(text):
    """Crude repetition detector: fraction of output taken by the most repeated 40-char window."""
    t = re.sub(r"\s+", " ", text)
    if len(t) < 240: return 0.0
    W, seen, best = 40, {}, 0
    for i in range(0, len(t) - W, 7):
        w = t[i:i+W]
        seen[w] = seen.get(w, 0) + 1
        best = max(best, seen[w])
    return round(best * W / len(t), 3)

DUR_TESTS = '''
assert parse_duration("1h30m") == 5400000, "1h30m"
assert parse_duration("-1h30m") == -5400000, "R1 whole-expression negation"
assert parse_duration("1h 1h") == 7200000, "R2 repeated units"
assert parse_duration("0.5ms") == 1, "R3 half-up"
assert parse_duration("1.4ms") == 1, "R3 down"
assert parse_duration("1.5ms") == 2, "R3 half-up"
assert parse_duration("-1.5ms") == -2, "R3 sign after magnitude"
assert parse_duration("2d") == 172800000, "days"
for bad in ("", "5", "10x", "  "):
    try:
        parse_duration(bad); raise SystemExit("should have raised: %r" % (bad,))
    except ValueError: pass
'''

ROUTE_TESTS = '''
assert route_match("/users/:id", "/users/42") == {"id": "42"}
assert route_match("/users/:id", "/users/42/") == {"id": "42"}, "R4 trailing slash"
assert route_match("/users/:id", "/users/") is None, "R6 empty capture is not a match"
assert route_match("/users/:id", "/users/42/x") is None
assert route_match("/files/*rest", "/files/a/b/c") == {"rest": "a/b/c"}
assert route_match("/files/*rest", "/files") == {"rest": ""}, "R3 zero-segment tail"
assert route_match("/files/*rest", "/files/") == {"rest": ""}, "R3+R4"
assert route_match("/", "/") == {}, "R5"
assert route_match("/", "/a") is None
assert route_match("/A/b", "/a/b") is None, "R1 case-sensitive"
'''

TOOLS = [{"type": "function", "function": {
    "name": "shard_rebalance",
    "description": "Rebalance shards across replicas.",
    "parameters": {"type": "object", "properties": {
        "shard_id": {"type": "string"},
        "target_replicas": {"type": "integer"},
        "drain_first": {"type": "boolean"}},
        "required": ["shard_id", "target_replicas"]}}}]

PROBES = [
    dict(id="needle_backoff", kind="needle", max_tokens=200,
         q="From the bundle above: what is the exact numeric value of RETRY_BACKOFF_MS? "
           "Answer with the number only.", want=NEEDLES["RETRY_BACKOFF_MS"]),
    dict(id="needle_replica", kind="needle", max_tokens=200,
         q="From the bundle above: what is the exact numeric value of SHARD_REPLICA_MIN? "
           "Answer with the number only.", want=NEEDLES["SHARD_REPLICA_MIN"]),
    dict(id="needle_audit", kind="needle", max_tokens=200,
         q="From the bundle above: what is the exact numeric value of AUDIT_FLUSH_ROWS? "
           "Answer with the number only.", want=NEEDLES["AUDIT_FLUSH_ROWS"]),
    dict(id="code_duration", kind="code", max_tokens=7000, tests=DUR_TESTS,
         q="Implement `parse_duration(s)` in Python exactly as specified in "
           "services/spec/DURATION.md above. Obey rules R1-R5 precisely. "
           "Output one ```python``` block containing only the function and its imports."),
    dict(id="code_route", kind="code", max_tokens=7000, tests=ROUTE_TESTS,
         q="Implement `route_match(pattern, path)` in Python exactly as specified in "
           "services/spec/ROUTES.md above. Obey rules R1-R6 precisely. "
           "Output one ```python``` block containing only the function and its imports."),
    dict(id="toolcall", kind="tool", max_tokens=800,
         q="Rebalance shard 'shard-77'. Use the minimum number of target replicas that the "
           "bundle's constants permit, and drain first. Call the tool."),
]

def ask(probe, effort="medium", salt=None):
    # Prefix caching matches from the FIRST byte. A unique leading block therefore
    # guarantees a cache MISS while leaving the semantic content byte-identical;
    # a fixed leading block guarantees the whole bundle is a cache HIT.
    head = "[session %s]\n" % (salt if salt is not None else "FIXED-0000")
    msgs = [{"role": "user", "content": head + PREFIX + "\n\n---\n\n" + probe["q"]}]
    payload = dict(model=MODEL, messages=msgs, temperature=1.0, top_p=0.95,
                   max_tokens=probe["max_tokens"], stream=False)
    payload["chat_template_kwargs"] = {"reasoning_effort": effort}
    if probe["kind"] == "tool":
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"
    t0 = time.time()
    r = post("/v1/chat/completions", payload)
    dt = time.time() - t0
    m = r["choices"][0]["message"]
    usage = r.get("usage", {})
    return m, dt, usage

def score(probe, msg):
    content = (msg.get("content") or "")
    detail = ""
    if probe["kind"] == "needle":
        ok = probe["want"] in content
        detail = content.strip()[:80]
    elif probe["kind"] == "code":
        ok, detail = run_tests(extract_code(content), probe["tests"])
    else:
        calls = msg.get("tool_calls") or []
        ok = False
        if len(calls) == 1 and calls[0].get("function", {}).get("name") == "shard_rebalance":
            try:
                args = json.loads(calls[0]["function"]["arguments"])
                ok = (args.get("shard_id") == "shard-77"
                      and args.get("target_replicas") == int(NEEDLES["SHARD_REPLICA_MIN"])
                      and args.get("drain_first") is True)
                detail = json.dumps(args)
            except Exception as e:
                detail = "bad json: %s" % e
        else:
            detail = "calls=%d leaked_content=%d chars" % (len(calls), len(content.strip()))
        # tool-call leakage: a tool call that also dumps JSON into the text body
        if content and re.search(r'\{\s*"(shard_id|name|arguments)"', content):
            detail += " | LEAKAGE: tool JSON in content"
            ok = False
    return ok, detail

def cache_delta(before, after):
    keys = [k for k in after if "hit" in k or "quer" in k]
    d = {}
    for k in sorted(keys):
        d[k] = round(after.get(k, 0) - before.get(k, 0), 1)
    q = sum(v for k, v in d.items() if "quer" in k)
    h = sum(v for k, v in d.items() if "hit" in k)
    d["_hit_rate_pct"] = round(100.0 * h / q, 1) if q else None
    return d

def run_pass(label, samples, effort):
    rows = []
    if label == "HOT":
        # warm the shared prefix once so every scored request lands on the cache-hit path
        ask(PROBES[0], effort, salt=None)
    m0 = metrics()
    for probe in PROBES:
        for s in range(samples):
            salt = ("%s-%s-%d-%d" % (label, probe["id"], s, int(time.time() * 1000))
                    if label == "COLD" else None)
            msg, dt, usage = ask(probe, effort, salt=salt)
            ok, detail = score(probe, msg)
            content = (msg.get("content") or "")
            rep = degeneracy(content)
            rows.append(dict(pass_=label, probe=probe["id"], sample=s, ok=ok, secs=round(dt, 1),
                             prompt_tok=usage.get("prompt_tokens"),
                             cached_tok=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                             out_tok=usage.get("completion_tokens"), repetition=rep, detail=detail))
            flag = "OK " if ok else "FAIL"
            print("%-5s %-15s s%d %s %6.1fs out=%-5s cached=%-7s rep=%.2f  %s" % (
                label, probe["id"], s, flag, dt, usage.get("completion_tokens"),
                (usage.get("prompt_tokens_details") or {}).get("cached_tokens"), rep, detail[:70]),
                flush=True)
    m1 = metrics()
    return rows, cache_delta(m0, m1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--tag", default="cachehit")
    a = ap.parse_args()

    print("prefix chars=%d (~%dK tokens est)" % (len(PREFIX), len(PREFIX) // 4000))
    print("probes=%d samples=%d effort=%s" % (len(PROBES), a.samples, a.effort))
    print()

    cold, cold_cache = run_pass("COLD", a.samples, a.effort)
    print("\n-- cold pass cache counters: %s\n" % json.dumps(cold_cache))
    hot, hot_cache = run_pass("HOT", a.samples, a.effort)
    print("\n-- hot pass cache counters: %s\n" % json.dumps(hot_cache))

    def summarize(rows):
        by = {}
        for r in rows:
            by.setdefault(r["probe"], []).append(r["ok"])
        return {k: "%d/%d" % (sum(v), len(v)) for k, v in by.items()}, \
               sum(r["ok"] for r in rows), len(rows)

    cs, cp, ct = summarize(cold)
    hs, hp, ht = summarize(hot)
    maxrep_c = max((r["repetition"] for r in cold), default=0)
    maxrep_h = max((r["repetition"] for r in hot), default=0)
    cached_h = [r["cached_tok"] for r in hot if r["cached_tok"] is not None]

    print("=" * 68)
    print("%-16s %-12s %-12s" % ("probe", "COLD", "HOT"))
    for k in cs:
        mark = "" if cs[k] == hs.get(k) else "   <-- DIFFERS"
        print("%-16s %-12s %-12s%s" % (k, cs[k], hs.get(k), mark))
    print("-" * 68)
    print("%-16s %-12s %-12s" % ("TOTAL", "%d/%d" % (cp, ct), "%d/%d" % (hp, ht)))
    print("%-16s %-12s %-12s" % ("max repetition", maxrep_c, maxrep_h))
    print("%-16s %-12s %-12s" % ("cache hit rate", cold_cache.get("_hit_rate_pct"),
                                 hot_cache.get("_hit_rate_pct")))
    print("%-16s %s" % ("hot cached_tokens", cached_h[:6]))
    print("=" * 68)

    verdict = []
    if hot_cache.get("_hit_rate_pct") in (None, 0, 0.0) and not any(cached_h):
        verdict.append("INCONCLUSIVE: the hot pass did not actually hit the prefix cache; "
                       "this test proves nothing about the cache-hit path.")
    else:
        if hp < cp:
            verdict.append("REGRESSION on cache-hit path: hot scored %d/%d vs cold %d/%d." % (hp, ht, cp, ct))
        elif hp == cp:
            verdict.append("NO REGRESSION: hot matched cold (%d/%d)." % (hp, ht))
        else:
            verdict.append("Hot scored HIGHER (%d/%d vs %d/%d) -- within sampling noise at temp 1.0." % (hp, ht, cp, ct))
        if maxrep_h > max(0.25, maxrep_c * 1.5):
            verdict.append("Degenerate repetition elevated on hot path (%.2f vs %.2f)." % (maxrep_h, maxrep_c))
    for v in verdict:
        print("VERDICT: " + v)

    out = "cachehit_%s.json" % a.tag
    json.dump(dict(cold=cold, hot=hot, cold_cache=cold_cache, hot_cache=hot_cache,
                   verdict=verdict), open(out, "w"), indent=1)
    print("wrote " + out)
    print("CACHEHIT_DONE")

if __name__ == "__main__":
    main()
