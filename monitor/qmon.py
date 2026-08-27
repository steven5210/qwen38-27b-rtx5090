#!/usr/bin/env python3
"""QMON -- unified live monitor for the Qwen3.8-27B machine. Zero dependencies.

Watches BOTH stacks and follows whichever is up (re-detects live, so it tracks
START-NINFER / STOP-NINFER transitions automatically):
  ninfer  :8080  (production)  -- parsed from prod.err completion + throughput lines
  vLLM    :8000  (fallback)    -- parsed from /metrics

Flicker-free: alternate screen buffer, cursor hidden, frames rewritten line-by-line
with EOL clears -- the screen is never blanked. QMON.bat / NMON.bat / MONITOR.bat all
launch this. Ctrl+C or close the window to quit; servers are unaffected.

v2 (2026-08-27): idle-aware now-stats (decode/sparkline drop to 0 the moment the queue
drains -- the last throughput line is only "now" while it is fresh AND reports work),
incremental log follow from byte 0 (session totals are exact for the whole server
session, not a 2MB tail), a state line (IDLE with time-since-last-request /
GENERATING with elapsed + ~tokens-so-far integrated from the 5s throughput lines +
max_tokens/thinking/tools from the submit line, plus a stall detector), a session
token-totals line, and a richer last-req line (out @ tok/s, wall). Env for testing:
QMON_ERR (log path), QMON_FORCE_STACK=ninfer (skip probing).
"""
import json, os, re, shutil, subprocess, sys, time, urllib.request

D = os.path.dirname(os.path.abspath(__file__))
NIN = os.environ.get("QMON_NINFER", "http://127.0.0.1:8080")
VLL = os.environ.get("QMON_VLLM",   "http://127.0.0.1:8000")
ERR = os.environ.get("QMON_ERR", "/opt/ninfer/logs/prod.err")
SERVE_LOG = os.path.join(D, "logs", "serve.log")
FORCE = os.environ.get("QMON_FORCE_STACK")
try: KEY = open(os.path.join(D, "api-key.txt")).read().strip()
except Exception: KEY = ""
HDRS = {"Authorization": "Bearer " + KEY} if KEY else {}

C = {"g":"\033[32m","y":"\033[33m","r":"\033[31m","c":"\033[36m","d":"\033[2m","b":"\033[1m","x":"\033[0m"}
def col(s, k): return C[k] + s + C["x"]
SPARK = "▁▂▃▄▅▆▇█"

def fetch(base, path, timeout=3):
    req = urllib.request.Request(base + path, headers=HDRS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def probe(base):
    try: return json.loads(fetch(base, "/v1/models"))["data"][0].get("id")
    except Exception: return None

def proc_uptime(pattern):
    """Real server uptime from the process table (survives monitor restarts)."""
    try:
        pid = subprocess.run(["pgrep", "-o", "-f", pattern], capture_output=True, text=True, timeout=4).stdout.split()
        if not pid: return None
        et = subprocess.run(["ps", "-o", "etimes=", "-p", pid[0]], capture_output=True, text=True, timeout=4).stdout.strip()
        return int(et) if et else None
    except Exception: return None

def fmt_up(secs):
    if secs is None: return "--"
    d, r = divmod(int(secs), 86400)
    return ("%dd " % d if d else "") + "%02d:%02d:%02d" % (r // 3600, r % 3600 // 60, r % 60)

def vram():
    try:
        o = subprocess.run(["nvidia-smi","--query-gpu=memory.used,memory.total",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        u, t = [int(x) for x in o.stdout.strip().split(",")]
        return u, t
    except Exception: return None, None

def tail_file(path, nbytes):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - nbytes))
            return f.read().decode("utf-8", "replace")
    except Exception: return ""

def head_file(path, nbytes):
    try:
        with open(path, "rb") as f:
            return f.read(nbytes).decode("utf-8", "replace")
    except Exception: return ""

def server_profile():
    """Authoritative window + vision flag from the running server's own boot line
    (prod.err is truncated at each boot, so the capacity line lives in the head)."""
    h = head_file(ERR, 8000)
    m = re.search(r"KV capacity \S+ resolved=(\d+) tokens", h)
    return (int(m.group(1)) if m else None), ("media-workers=" in h)

def conf_ctx():
    try:
        t = open(os.path.join(D, "ninfer-prod.conf")).read()
        m = re.search(r"^CTX=(\d+)", t, re.M)
        return int(m.group(1)) if m else None
    except Exception: return None

def bar(p, w):
    p = max(0.0, min(p, 1.0)); f = int(w * p)
    return "█" * f + "░" * (w - f)

def spark(vals, w):
    vals = vals[-w:]
    if not vals: return ""
    hi = max(max(vals), 1e-9)
    return "".join(SPARK[min(7, int(8 * v / hi))] if v > 0 else " " for v in vals)

def fmt_tok(n): return format(int(n), ",")

RE_DONE = re.compile(
    r"\[req (\d+)\] done finish=(\S+)(?: tool_calls=(\d+))? prompt=(\d+) gen=(\d+) cache=(\d+) "
    r"reuse=(\S+) ttft=(\d+)ms(?: prefill=([\d.]+)tok/s)?(?: decode=([\d.]+)tok/s)?"
    r"(?: wall=([\d.]+)s)?(?: speculative=\S+ ([\d.]+)tok/round \(([\d.]+)%\))?")
RE_THR  = re.compile(r"throughput interval=([\d.]+)s prefill=([\d.]+)tok/s decode=([\d.]+)tok/s running=(\d+) prefilling=(\d+) decode_ready=(\d+) waiting=(\d+)")
RE_TS   = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.(\d{3})\]")

def line_ts(l):
    m = RE_TS.match(l)
    if not m: return None
    try:
        return time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) + int(m.group(2)) / 1000.0
    except Exception:
        return None

def fmt_dur(s):
    s = max(0, int(s))
    if s < 90: return "%ds" % s
    if s < 3600: return "%dm%02ds" % (s // 60, s % 60)
    return "%dh%02dm" % (s // 3600, s % 3600 // 60)

class NinferLog:
    """Incremental follower of ninfer's prod.err. The file is truncated at every
    server boot, so parsing from byte 0 makes the accumulated stats exactly the
    server session. Only new bytes are read each frame; a size drop means the
    server rebooted and all session state resets."""
    def __init__(self, path):
        self.path = path
        self.reset()
    def reset(self):
        self.off = 0
        self.buf = b""
        self.reqs = []            # completed requests (display window; sums are lifetime)
        self.sums = {"n": 0, "p": 0, "g": 0, "c": 0, "ttft_ms": 0, "wall": 0.0,
                     "dec_g": 0, "dec_t": 0.0, "mtp_g": 0, "mtp_gx": 0.0}
        self.fin = {}
        self.subs = {}            # req id -> {"ts","max_tokens","tools","thinking"} while in flight
        self.thr = None           # last throughput line, parsed
        self.live_gen = 0.0       # ~tokens generated across the current in-flight request(s)
    def poll(self):
        try: size = os.path.getsize(self.path)
        except Exception: return
        if size < self.off: self.reset()          # truncated -> new server session
        if size == self.off: return
        try:
            with open(self.path, "rb") as f:
                f.seek(self.off)
                data = self.buf + f.read(size - self.off)
                self.off = size
        except Exception:
            return
        lines = data.split(b"\n")
        self.buf = lines.pop()                    # keep any partial trailing line
        for raw in lines:
            self._line(raw.decode("utf-8", "replace"))
    def _line(self, l):
        if "throughput interval=" in l:
            m = RE_THR.search(l)
            if not m: return
            iv, pre, dec = float(m.group(1)), float(m.group(2)), float(m.group(3))
            self.thr = {"ts": line_ts(l), "interval": iv, "prefill": pre, "decode": dec,
                        "running": int(m.group(4)), "prefilling": int(m.group(5)),
                        "ready": int(m.group(6)), "waiting": int(m.group(7))}
            if self.subs and dec > 0:
                self.live_gen += dec * iv
            return
        if "] done " in l:
            m = RE_DONE.search(l)
            if not m: return
            r = {"id": m.group(1), "finish": m.group(2), "p": int(m.group(4)),
                 "g": int(m.group(5)), "c": int(m.group(6)), "path": m.group(7),
                 "ttft_ms": int(m.group(8)), "prefill": m.group(9), "dec": m.group(10),
                 "wall": float(m.group(11)) if m.group(11) else None,
                 "mtp_r": m.group(12), "mtp": m.group(13), "ts": line_ts(l)}
            self.reqs.append(r); self.reqs[:] = self.reqs[-500:]
            s = self.sums
            s["n"] += 1; s["p"] += r["p"]; s["g"] += r["g"]; s["c"] += r["c"]
            s["ttft_ms"] += r["ttft_ms"]
            if r["wall"]: s["wall"] += r["wall"]
            if r["dec"] and float(r["dec"]) > 0:
                s["dec_g"] += r["g"]; s["dec_t"] += r["g"] / float(r["dec"])
            if r["mtp"]:
                s["mtp_g"] += r["g"]; s["mtp_gx"] += r["g"] * float(r["mtp"])
            self.fin[r["finish"]] = self.fin.get(r["finish"], 0) + 1
            self.subs.pop(r["id"], None)
            self.live_gen = max(0.0, self.live_gen - r["g"]) if self.subs else 0.0
            return
        if "] openai_" in l and "submitted" in l:
            mi = re.search(r"\[req (\d+)\]", l)
            if not mi: return
            def grab(pat):
                mm = re.search(pat, l); return mm.group(1) if mm else None
            self.subs[mi.group(1)] = {"ts": line_ts(l),
                                      "max_tokens": grab(r"max_tokens=(\d+)"),
                                      "tools": grab(r"tools=(\d+)"),
                                      "thinking": grab(r"thinking=(\w+)")}
            return
        m = re.search(r"\[req (\d+)\][^\n]*?(error|failed|abort|cancel|disconnect)", l, re.I)
        if m:
            self.subs.pop(m.group(1), None)
            if not self.subs: self.live_gen = 0.0
    def now_state(self, now):
        """-> (active, dec_now, pre_now, run, wai, stall_secs).
        Idle the moment the last throughput line reports empty queues, or when
        throughput lines stop arriving (they print every ~5s only while working)."""
        t = self.thr
        fresh = bool(t and t["ts"] and now - t["ts"] <= 7.5)
        queues0 = bool(t) and (t["running"] + t["prefilling"] + t["ready"] + t["waiting"] == 0)
        if self.subs and fresh and queues0:
            self.subs.clear(); self.live_gen = 0.0   # ended without a done line (client gone)
        active = bool(self.subs) or (fresh and not queues0)
        dec_now = t["decode"] if (t and fresh and active) else 0.0
        pre_now = t["prefill"] if (t and fresh and active) else 0.0
        run = t["running"] if (t and fresh) else (1 if self.subs else 0)
        wai = t["waiting"] if (t and fresh) else 0
        stall = 0.0
        if self.subs and not fresh:
            ref = t["ts"] if (t and t["ts"]) else max(v["ts"] or now for v in self.subs.values())
            stall = now - ref
        return active, dec_now, pre_now, run, wai, stall

class Screen:
    def __init__(self, once):
        self.once = once
        self.active = False
    def __enter__(self):
        if not self.once:
            sys.stdout.write("\033[?1049h\033[?25l\033[H\033[J"); sys.stdout.flush()
            self.active = True
        return self
    def __exit__(self, *a):
        if self.active:
            sys.stdout.write("\033[?25h\033[?1049l"); sys.stdout.flush()
    def draw(self, lines):
        if self.once:
            sys.stdout.write("\n".join(lines) + "\n"); sys.stdout.flush(); return
        out = ["\033[H"]
        for ln in lines:
            out.append(ln + "\033[K\n")
        out.append("\033[J")
        sys.stdout.write("".join(out)); sys.stdout.flush()

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    stack = None            # "ninfer" | "vllm" | None
    model = None; boot_t0 = time.time(); up_secs = None
    vr_u = vr_t = None; vr_base = None; tick = 0
    dec_hist = []           # decode tok/s history for sparkline
    nlog = NinferLog(ERR)   # incremental session parser (survives stack-probe blips)
    # vLLM state
    prev_gen = None; prev_t = None; ema = None; ring = []; pool = None; mml = None

    with Screen(a.once) as scr:
        while True:
            tick += 1
            width = max(64, min(shutil.get_terminal_size((80, 24)).columns - 2, 100))
            H = "─" * width
            now = time.time(); clock = time.strftime("%H:%M:%S")
            if tick % 3 == 1:
                u, t = vram()
                if u: vr_u, vr_t = u, t

            # ---- detect / follow the live stack ----
            if FORCE:
                mid = model or "qwen3.8-27b"; new_stack = FORCE
            else:
                mid = probe(NIN)
                new_stack = "ninfer" if mid else None
                if not new_stack:
                    mid = probe(VLL)
                    new_stack = "vllm" if mid else None
            if new_stack != stack:
                stack = new_stack; model = mid
                vr_base = None; dec_hist = []; ring = []; prev_gen = None; ema = None
                pool = None; mml = None
                if stack and not a.once: sys.stdout.write("\a")
                if not stack: boot_t0 = time.time()
                up_secs = None
            if stack:
                if up_secs is None or tick % 3 == 1:
                    up_secs = proc_uptime("ninfer-serve" if stack == "ninfer" else "vllm serve")
                elif up_secs is not None:
                    up_secs += a.interval
            else:
                up_secs = None

            L = []
            L.append(col("  QWEN 3.8-27B MONITOR", "b") +
                     ("   %s" % clock).rjust(width - 22))
            if stack is None:
                L.append(H)
                L.append("  " + col("NO SERVER UP", "r") + col("   (watching :8080 ninfer and :8000 vLLM)", "d"))
                L.append("  waiting %ds" % (now - boot_t0))
                nerr = tail_file(ERR, 4000).strip().splitlines()
                serr = tail_file(SERVE_LOG, 200_000).strip().splitlines()
                if nerr: L.append(col("  ninfer log: ", "d") + nerr[-1][:width - 15])
                sl = next((l for l in reversed(serr) if l and not l.startswith("+")), "")
                if sl:   L.append(col("  vLLM  log: ", "d") + sl[:width - 15])
                L.append(H)
                L.append(col("  START-NINFER.bat (10s) or START-QWEN38.bat (~2.5min) to boot", "d"))
            elif stack == "ninfer":
                srv_ctx, srv_vision = server_profile()
                ctx = srv_ctx or conf_ctx() or 252928
                nlog.poll()
                active, dec, pre, run, wai, stall = nlog.now_state(now)
                dec_hist.append(dec); dec_hist[:] = dec_hist[-60:]
                s = nlog.sums; reqs = nlog.reqs
                L.append("  " + col("READY", "g") + "  %s  " % model +
                         (col("VISION", "c") + "  " if srv_vision else "") +
                         col("ninfer :8080  window %s (server-reported)  up %s" %
                             (fmt_tok(ctx), fmt_up(up_secs)), "d"))
                L.append(H)
                # ---- state line: what is happening RIGHT NOW ----
                if nlog.subs:
                    ids = sorted(nlog.subs, key=lambda k: int(k))
                    sub = nlog.subs[ids[0]]
                    el = (now - sub["ts"]) if sub["ts"] else 0
                    if len(ids) == 1:
                        seg = "GENERATING #%s · %s" % (ids[0], fmt_dur(el))
                        if nlog.live_gen > 0:
                            seg += " · ~%s tok so far" % fmt_tok(nlog.live_gen)
                            if sub["max_tokens"]: seg += " (max %s)" % fmt_tok(int(sub["max_tokens"]))
                        fl = []
                        if sub["thinking"]: fl.append("thinking %s" % sub["thinking"])
                        if sub["tools"] and sub["tools"] != "0": fl.append("tools %s" % sub["tools"])
                        if fl: seg += " · " + " · ".join(fl)
                    else:
                        seg = "GENERATING %d reqs (#%s) · oldest %s" % (len(ids), " #".join(ids), fmt_dur(el))
                        if nlog.live_gen > 0: seg += " · ~%s tok combined" % fmt_tok(nlog.live_gen)
                    state_ln = "  state     " + col(seg, "c")
                    if stall > 12:
                        state_ln += "  " + col("no throughput for %s -- possible stall" % fmt_dur(stall),
                                               "r" if stall > 60 else "y")
                    state_line = state_ln
                elif reqs:
                    ago = fmt_dur(now - reqs[-1]["ts"]) if reqs[-1]["ts"] else "--"
                    state_line = "  state     " + col("IDLE · %s since last request" % ago, "d")
                else:
                    state_line = "  state     " + col("IDLE · no requests yet this session", "d")
                if reqs:
                    r = reqs[-1]
                    pct = r["p"] / ctx
                    L.append("  context   [%s] %s / %s  %d%%" %
                             (bar(pct, width - 42), fmt_tok(r["p"]), fmt_tok(ctx), round(100 * pct)))
                    glyph = {"append_frontier": col("append ✓", "g"),
                             "full_reset": col("reset", "y")}.get(r["path"],
                             col(r["path"].replace("restore_", "restore ") + " ↻", "c"))
                    seg = "prompt %s · cached %s (%d%%) · %s · out %s" % (
                        fmt_tok(r["p"]), fmt_tok(r["c"]),
                        round(100.0 * r["c"] / r["p"]) if r["p"] else 0, glyph, fmt_tok(r["g"]))
                    if r["dec"]: seg += " @ %s tok/s" % r["dec"]
                    if r["wall"]: seg += " · wall %s" % fmt_dur(r["wall"])
                    seg += " · ttft %.2fs" % (r["ttft_ms"] / 1000.0)
                    L.append(col("  last req  ", "d") + seg)
                    L.append(state_line)
                    fintxt = " · ".join("%s %d" % (k.replace("tool_calls", "tool"), v)
                                        for k, v in sorted(nlog.fin.items()))
                    ntr = nlog.fin.get("length", 0) + nlog.fin.get("output_limit", 0)
                    if ntr: fintxt = col(fintxt + "  << %d truncated (raise max output?)" % ntr, "y")
                    left = "  requests  running %d · waiting %d" % (run, wai)
                    L.append((col(left, "y") if wai else left) + "      finish: %s" % fintxt)
                    last10 = reqs[-10:]
                    def wavg(pairs):
                        tt = sum(g / rr for g, rr in pairs if rr > 0); gg = sum(g for g, rr in pairs)
                        return gg / tt if tt > 0 else 0.0
                    d10 = [(r2["g"], float(r2["dec"])) for r2 in last10 if r2["dec"]]
                    avg_dec = s["dec_g"] / s["dec_t"] if s["dec_t"] > 0 else 0.0
                    L.append("  decode    %7.1f tok/s now  %s" % (dec, col(spark(dec_hist, width - 58), "c")) +
                             col("  avg %5.1f · last-10 %5.1f" % (avg_dec, wavg(d10)), "d"))
                    L.append("  prefill   %7.1f tok/s now   last req %s tok/s" % (pre, r["prefill"] or "--"))
                    if s["mtp_g"]:
                        L.append("  mtp       %s%% accept last (%s tok/round)   session %.1f%%" %
                                 (r["mtp"] or "--", r["mtp_r"] or "-", s["mtp_gx"] / s["mtp_g"]))
                    t10 = [r2["ttft_ms"] for r2 in last10]
                    L.append("  ttft      last %.2fs · last-10 avg %.2fs · session avg %.2fs" %
                             (r["ttft_ms"] / 1000.0, sum(t10) / len(t10) / 1000.0,
                              s["ttft_ms"] / s["n"] / 1000.0))
                    L.append("  tokens    prompt %s + out %s = %s session total · cache-served %s (%d%%)" %
                             (fmt_tok(s["p"]), fmt_tok(s["g"]), fmt_tok(s["p"] + s["g"]),
                              fmt_tok(s["c"]), round(100.0 * s["c"] / s["p"]) if s["p"] else 0))
                    c10p = sum(r2["p"] for r2 in last10)
                    busy = min(1.0, s["wall"] / max(1.0, up_secs or 1)) if s["wall"] else 0.0
                    L.append("  session   %d req%s · busy %d%% · cache hit last-10 %d%%" %
                             (s["n"], "" if s["n"] == 1 else "s", round(100 * busy),
                              round(100.0 * sum(r2["c"] for r2 in last10) / c10p) if c10p else 0))
                else:
                    L.append(state_line)
                    reqline = "  requests  running %d · waiting %d      (no completions logged yet)" % (run, wai)
                    L.append(col(reqline, "y") if wai else reqline)
                    L.append("  decode    %7.1f tok/s now  %s" % (dec, col(spark(dec_hist, width - 40), "c")))
                    L.append("  prefill   %7.1f tok/s now" % pre)
            else:  # vllm
                try:
                    mtx = {}
                    for ln in fetch(VLL, "/metrics", 4).splitlines():
                        if not ln or ln.startswith("#"): continue
                        m = re.match(r'^(\S+?)(\{[^}]*\})?\s+([0-9.eE+\-]+)\s*$', ln.strip())
                        if m:
                            try: mtx[m.group(1)] = mtx.get(m.group(1), 0.0) + float(m.group(3))
                            except ValueError: pass
                    if mml is None:
                        mj = json.loads(fetch(VLL, "/v1/models"))["data"][0]
                        mml = mj.get("max_model_len")
                        t_ = tail_file(SERVE_LOG, 6_000_000)
                        pm = re.findall(r"GPU KV cache size:\s*([0-9,]+)", t_)
                        pool = int(pm[-1].replace(",", "")) if pm else None
                    gen = mtx.get("vllm:generation_tokens_total", 0.0)
                    if prev_gen is not None and gen < prev_gen: raise RuntimeError("restart")
                    if prev_t and now > prev_t:
                        inst = (gen - (prev_gen or gen)) / (now - prev_t)
                        ema = inst if ema is None else 0.6 * ema + 0.4 * inst
                    prev_gen = gen; prev_t = now
                    kvp = mtx.get("vllm:kv_cache_usage_perc", 0.0)
                    pq, ph = mtx.get("vllm:prefix_cache_queries_total", 0.0), mtx.get("vllm:prefix_cache_hits_total", 0.0)
                    ac, dr = mtx.get("vllm:spec_decode_num_accepted_tokens_total", 0.0), mtx.get("vllm:spec_decode_num_draft_tokens_total", 0.0)
                    ring.append((now, ph, pq, ac, dr)); ring[:] = [r for r in ring if now - r[0] <= 60]
                    w0 = ring[0]
                    def win(cur, old, cq, oq): d = cq - oq; return 100.0 * (cur - old) / d if d > 0 else None
                    hit60, acc60 = win(ph, w0[1], pq, w0[2]), win(ac, w0[3], dr, w0[4])
                    dec_hist.append(ema or 0.0); dec_hist[:] = dec_hist[-60:]
                    L.append("  " + col("READY", "g") + "  %s  " % model + col("vLLM :8000 (fallback)  up %s" % fmt_up(up_secs), "d"))
                    L.append(H)
                    est = kvp * (pool or 0)
                    L.append("  KV pool   [%s] %5.1f%%   %s tok incl. retained cache" %
                             (bar(kvp, width - 48), kvp * 100, fmt_tok(est)))
                    L.append("  window    %s   usable prompt @16K out: %s   pool %s" %
                             (fmt_tok(mml) if mml else "?", fmt_tok(mml - 16384) if mml else "?",
                              fmt_tok(pool) if pool else "?"))
                    L.append("  requests  running %d  waiting %d" %
                             (int(mtx.get("vllm:num_requests_running", 0)), int(mtx.get("vllm:num_requests_waiting", 0))))
                    L.append("  decode    %7.1f tok/s  %s" % (ema or 0.0, col(spark(dec_hist, width - 40), "c")))
                    L.append("  prefix    %s lifetime   %s last 60s" %
                             ("%5.1f%%" % (100.0 * ph / pq) if pq else "  n/a",
                              "%5.1f%%" % hit60 if hit60 is not None else "   --"))
                    L.append("  mtp       %s lifetime   %s last 60s" %
                             ("%5.1f%%" % (100.0 * ac / dr) if dr else "  n/a",
                              "%5.1f%%" % acc60 if acc60 is not None else "   --"))
                    L.append(col("  lifetime  ", "d") + "prompt %s   output %s" %
                             (fmt_tok(mtx.get("vllm:prompt_tokens_total", 0.0)), fmt_tok(gen)))
                except Exception:
                    stack = None; continue

            if stack and vr_u:
                free = vr_t - vr_u
                if vr_base is None or vr_u < vr_base: vr_base = vr_u
                growth = vr_u - vr_base
                if stack == "vllm":
                    st = col("[OK]", "g") if free >= 2100 else (col("[CAUTION <2.1GB free: cached TTFT degrades]", "y")
                         if free >= 1500 else col("[DANGER <1.5GB free: Windows WILL page, 10x]", "r"))
                else:
                    st = col("[OK -- fixed pool, slim free is by design]", "g") if growth < 400 else \
                         col("[CAUTION +%d MiB above boot baseline -- desktop apps eating VRAM?]" % growth, "y")
                L.append("  vram      %s / %s MiB   free %s   %s" % (fmt_tok(vr_u), fmt_tok(vr_t), fmt_tok(free), st))
            if stack == "ninfer" and len(nlog.reqs) >= 2:
                L.append(H)
                L.append(col("  recent", "d"))
                for r_ in nlog.reqs[-4:][::-1]:
                    L.append(col("    #%-4s %9sp %9sc %8sg  %-16s %5.2fs ttft  %6s tok/s  %s%%mtp" %
                             (r_["id"], fmt_tok(r_["p"]), fmt_tok(r_["c"]), fmt_tok(r_["g"]),
                              r_["path"][:16], r_["ttft_ms"] / 1000.0,
                              r_["dec"] or "--", r_["mtp"] or "--"), "d"))
            L.append(H)
            L.append(col("  Ctrl+C or close window to quit -- servers unaffected", "d"))
            scr.draw(L)
            if a.once: return
            time.sleep(a.interval)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
