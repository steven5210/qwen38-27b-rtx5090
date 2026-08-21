#!/usr/bin/env python3
"""QMON -- unified live monitor for the Qwen3.8-27B machine. Zero dependencies.

Watches BOTH stacks and follows whichever is up (re-detects live, so it tracks
START-NINFER / STOP-NINFER transitions automatically):
  ninfer  :8080  (production)  -- parsed from prod.err completion + throughput lines
  vLLM    :8000  (fallback)    -- parsed from /metrics

Flicker-free: alternate screen buffer, cursor hidden, frames rewritten line-by-line
with EOL clears -- the screen is never blanked. QMON.bat / NMON.bat / MONITOR.bat all
launch this. Ctrl+C or close the window to quit; servers are unaffected.
"""
import json, os, re, shutil, subprocess, sys, time, urllib.request

D = os.path.dirname(os.path.abspath(__file__))
NIN = os.environ.get("QMON_NINFER", "http://127.0.0.1:8080")
VLL = os.environ.get("QMON_VLLM",   "http://127.0.0.1:8000")
ERR = "/opt/ninfer/logs/prod.err"
SERVE_LOG = os.path.join(D, "logs", "serve.log")
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
RE_THR  = re.compile(r"throughput interval=[\d.]+s prefill=([\d.]+)tok/s decode=([\d.]+)tok/s running=(\d+) prefilling=(\d+) decode_ready=(\d+) waiting=(\d+)")

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
                ctx = conf_ctx() or 252928
                txt = tail_file(ERR, 2_000_000)
                reqs = [RE_DONE.search(l) for l in txt.splitlines() if "] done " in l]
                reqs = [m for m in reqs if m]
                thr  = [RE_THR.search(l) for l in txt.splitlines() if "throughput" in l]
                thr  = [m for m in thr if m]
                pre = dec = 0.0; run = wai = 0
                if thr:
                    t_ = thr[-1]; pre, dec = float(t_.group(1)), float(t_.group(2))
                    run, wai = int(t_.group(3)), int(t_.group(6))
                dec_hist.append(dec); dec_hist[:] = dec_hist[-60:]
                L.append("  " + col("READY", "g") + "  %s  " % model +
                         col("ninfer :8080  up %s" % fmt_up(up_secs), "d"))
                L.append(H)
                if reqs:
                    m_ = reqs[-1]
                    p_, g_, c_ = int(m_.group(4)), int(m_.group(5)), int(m_.group(6))
                    path, ttft = m_.group(7), int(m_.group(8)) / 1000.0
                    pct = p_ / ctx
                    L.append("  context   [%s] %s / %s  %d%%" %
                             (bar(pct, width - 42), fmt_tok(p_), fmt_tok(ctx), round(100 * pct)))
                    glyph = {"append_frontier": col("append ✓", "g"),
                             "full_reset": col("reset", "y")}.get(path,
                             col(path.replace("restore_", "restore ") + " ↻", "c"))
                    L.append(col("  last req  ", "d") + "prompt %s   cached %s (%d%%)   %s   ttft %.2fs" %
                             (fmt_tok(p_), fmt_tok(c_), round(100.0 * c_ / p_) if p_ else 0, glyph, ttft))
                    # ---- session aggregates from the completion lines ----
                    P = [int(m.group(4)) for m in reqs]; G = [int(m.group(5)) for m in reqs]
                    CC = [int(m.group(6)) for m in reqs]; T = [int(m.group(8)) for m in reqs]
                    DEC = [(g, float(m.group(10))) for g, m in zip(G, reqs) if m.group(10)]
                    WALL = [float(m.group(11)) for m in reqs if m.group(11)]
                    ACC = [(g, float(m.group(13))) for g, m in zip(G, reqs) if m.group(13)]
                    def wavg(pairs):
                        tt = sum(g / r for g, r in pairs if r > 0); gg = sum(g for g, r in pairs)
                        return gg / tt if tt > 0 else 0.0
                    avg_dec = wavg(DEC); last10_dec = wavg(DEC[-10:])
                    fin = {}
                    for m in reqs: fin[m.group(2)] = fin.get(m.group(2), 0) + 1
                    fintxt = " · ".join("%s %d" % (k.replace("tool_calls", "tool"), v) for k, v in sorted(fin.items()))
                    ntr = fin.get("length", 0) + fin.get("output_limit", 0)
                    if ntr: fintxt = col(fintxt + "  << %d truncated (raise max output?)" % ntr, "y")
                    hits = [c for c in CC if c > 0]
                    busy = min(1.0, sum(WALL) / max(1.0, up_secs or 1)) if WALL else 0.0
                    L.append("  requests  running %d  waiting %d      finish: %s" % (run, wai, fintxt))
                    L.append("  decode    %7.1f tok/s now  %s" % (dec, col(spark(dec_hist, width - 58), "c")) +
                             col("  avg %5.1f · last-10 %5.1f" % (avg_dec, last10_dec), "d"))
                    L.append("  prefill   %7.1f tok/s now   last req %s tok/s" %
                             (pre, m_.group(9) or "--"))
                    if ACC:
                        sess_acc = sum(g * a2 for g, a2 in ACC) / max(1, sum(g for g, _ in ACC))
                        L.append("  mtp       %s%% accept last (%s tok/round)   session %.1f%%" %
                                 (m_.group(13) or "--", m_.group(12) or "-", sess_acc))
                    L.append("  ttft      last %.2fs · last-10 avg %.2fs · session avg %.2fs" %
                             (ttft, sum(T[-10:]) / len(T[-10:]) / 1000.0, sum(T) / len(T) / 1000.0))
                    L.append("  session   %d reqs · out %s · prompt %s (%s%% served from cache) · busy %d%%" %
                             (len(reqs), fmt_tok(sum(G)), fmt_tok(sum(P)),
                              round(100.0 * sum(CC) / sum(P)) if sum(P) else 0, round(100 * busy)))
                else:
                    L.append("  requests  running %d  waiting %d      (no completions logged yet)" % (run, wai))
                    L.append("  decode    %7.1f tok/s  %s" % (dec, col(spark(dec_hist, width - 40), "c")))
                    L.append("  prefill   %7.1f tok/s" % pre)
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
            if stack == "ninfer":
                txt2 = locals().get("reqs") or []
                if len(txt2) >= 2:
                    L.append(H)
                    L.append(col("  recent", "d"))
                    for m_ in txt2[-4:][::-1]:
                        L.append(col("    #%-4s %9sp %9sc  %-16s %5.2fs ttft  %6s tok/s  %s%%mtp" %
                                 (m_.group(1), fmt_tok(m_.group(4)), fmt_tok(m_.group(6)),
                                  m_.group(7)[:16], int(m_.group(8)) / 1000.0,
                                  m_.group(10) or "--", m_.group(13) or "--"), "d"))
            L.append(H)
            L.append(col("  Ctrl+C or close window to quit -- servers unaffected", "d"))
            scr.draw(L)
            if a.once: return
            time.sleep(a.interval)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
