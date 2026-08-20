#!/usr/bin/env python3
"""Live monitor for the Qwen3.8-27B vLLM server. Zero dependencies (urllib only).

Shows: boot progress -> READY banner, KV pool usage, decode tok/s, prefix-cache hit
rate, MTP acceptance, and VRAM with warnings at the measured paging thresholds.

  MONITOR.bat            (Windows)  |  python3 monitor.py [--interval 2] [--once]
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.error
D = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("QWEN_URL", "http://127.0.0.1:8000")
try: KEY = open(os.path.join(D, "api-key.txt")).read().strip()
except Exception: KEY = ""
HDRS = {"Authorization": "Bearer " + KEY} if KEY else {}
SERVE_LOG = os.path.join(D, "logs", "serve.log")
MLINE = re.compile(r'^(\S+?)(\{[^}]*\})?\s+([0-9.eE+\-]+)\s*$')

def fetch(path, timeout=4):
    req = urllib.request.Request(BASE + path, headers=HDRS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def metrics():
    out = {}
    for ln in fetch("/metrics").splitlines():
        if not ln or ln.startswith("#"): continue
        m = MLINE.match(ln.strip())
        if not m: continue
        n, lab, v = m.groups()
        try: out[n] = out.get(n, 0.0) + float(v)
        except ValueError: pass
        if n == "vllm:cache_config_info" and lab: out["_cache_labels"] = lab
    return out

def pool_from_serve_log():
    try:
        with open(SERVE_LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(SERVE_LOG) - 6_000_000))
            txt = f.read().decode("utf-8", "replace")
        m = re.findall(r"GPU KV cache size:\s*([0-9,]+)", txt)
        return int(m[-1].replace(",", "")) if m else None
    except Exception: return None

def boot_progress_line():
    try:
        with open(SERVE_LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(SERVE_LOG) - 200_000))
            lines = [l.strip() for l in f.read().decode("utf-8", "replace").splitlines()]
        for l in reversed(lines):
            if l and not l.startswith("+") and "sleep" not in l:
                return l[:74]
    except Exception: pass
    return "(no serve.log yet)"

def vram():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        u, t = [int(x) for x in o.stdout.strip().split(",")]
        return u, t
    except Exception: return None, None

def bar(p, w=36):
    f = int(w * max(0.0, min(p, 1.0)))
    return "#" * f + "-" * (w - f)

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    model_id = None; mml = None; pool = None
    ready_at = None; boot_watch_t0 = time.time()
    prev = {}; prev_t = None; ema = None
    ring = []          # (t, gen, pq, ph, acc, drf) for 60s windows
    vr_u = vr_t = None; tick = 0

    while True:
        tick += 1
        try:
            if model_id is None:
                mj = json.loads(fetch("/v1/models"))["data"][0]
                model_id = mj["id"]; mml = mj.get("max_model_len")
                pool = pool_from_serve_log()
                ready_at = time.time()
                print("\a", end="")
            m = metrics()
        except Exception:
            print("\033[H\033[J", end="")
            print("=" * 64)
            print("  QWEN MONITOR  --  SERVER NOT READY")
            print("=" * 64)
            print("  waiting %ds  (warm boot ~2.5 min; first boot ~5 min)" % (time.time() - boot_watch_t0))
            print("  serve.log: %s" % boot_progress_line())
            print("  start the server with START-QWEN38.bat if it isn't running")
            print("=" * 64)
            if a.once: return
            model_id = None; ready_at = None
            time.sleep(a.interval); continue

        gen  = m.get("vllm:generation_tokens_total", 0.0)
        pt   = m.get("vllm:prompt_tokens_total", 0.0)
        run  = int(m.get("vllm:num_requests_running", 0))
        wait = int(m.get("vllm:num_requests_waiting", 0))
        kvp  = m.get("vllm:kv_cache_usage_perc", 0.0)
        pq   = m.get("vllm:prefix_cache_queries_total", 0.0)
        ph   = m.get("vllm:prefix_cache_hits_total", 0.0)
        acc  = m.get("vllm:spec_decode_num_accepted_tokens_total", 0.0)
        drf  = m.get("vllm:spec_decode_num_draft_tokens_total", 0.0)

        now = time.time()
        if prev and gen < prev.get("gen", 0):     # counter reset = server restarted
            prev = {}; ring = []; model_id = None; continue
        if prev_t and now > prev_t:
            inst = (gen - prev.get("gen", gen)) / (now - prev_t)
            ema = inst if ema is None else (0.6 * ema + 0.4 * inst)
        prev = dict(gen=gen); prev_t = now
        ring.append((now, gen, pq, ph, acc, drf))
        ring[:] = [r for r in ring if now - r[0] <= 60]
        w = ring[0] if ring else None
        def rate(cur, old, curq, oldq):
            dq = curq - oldq
            return (100.0 * (cur - old) / dq) if dq > 0 else None
        hit60 = rate(ph, w[3], pq, w[2]) if w else None
        acc60 = rate(acc, w[5], drf, w[4]) if w else None
        if tick % 3 == 1: vr_u, vr_t = vram()

        est = kvp * (pool or 0)
        print("\033[H\033[J", end="")
        print("=" * 64)
        up = time.strftime("%H:%M:%S", time.gmtime(now - ready_at)) if ready_at else "--"
        print("  READY  %s   up %s" % (model_id, up))
        print("  window %s | usable prompt @16K out: %s | pool %s" %
              (f"{mml:,}" if mml else "?", f"{mml-16384:,}" if mml else "?", f"{pool:,}" if pool else "?"))
        print("-" * 64)
        print("  KV pool used  [%s] %5.1f%%" % (bar(kvp), kvp * 100))
        print("                %s tokens incl. retained prefix cache" % f"{int(est):,}")
        print("  requests      running %d | waiting %d" % (run, wait))
        print("  decode        %6.1f tok/s now   | lifetime out %s / prompt %s" %
              (ema or 0.0, f"{int(gen):,}", f"{int(pt):,}"))
        print("  prefix cache  %s lifetime | last 60s %s" %
              ("%5.1f%%" % (100.0 * ph / pq) if pq else "  n/a",
               "%5.1f%%" % hit60 if hit60 is not None else "  --"))
        print("  MTP accept    %s lifetime | last 60s %s" %
              ("%5.1f%%" % (100.0 * acc / drf) if drf else "  n/a",
               "%5.1f%%" % acc60 if acc60 is not None else "  --"))
        if vr_u:
            free = vr_t - vr_u
            state = "OK" if free >= 2100 else ("CAUTION <2.1GB: cached TTFT degrades" if free >= 1500
                     else "!! DANGER <1.5GB: Windows WILL page, 10x slowdown")
            print("  VRAM          %s / %s MiB   free %s   [%s]" %
                  (f"{vr_u:,}", f"{vr_t:,}", f"{free:,}", state))
        print("=" * 64)
        print("  Ctrl+C or close window to quit (server unaffected)")
        if a.once: return
        time.sleep(a.interval)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\nStopped (server unaffected).")
