#!/usr/bin/env python3
"""Deep-think mode: one hard question at reasoning_effort=xhigh with real room.

Why this exists: xhigh needs 15K-48K+ output tokens (measured), and inside Cline the prompt
eats the budget so it truncates. Here the prompt is small, so nearly the whole 106,496-token
window is available for reasoning -- which is the only configuration on a 32GB card where
xhigh reliably finishes.

  ask-xhigh.py "your question"
  ask-xhigh.py --file question.txt
  ask-xhigh.py --file bug.py --effort medium --max-tokens 30000
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
D=os.path.dirname(os.path.abspath(__file__))
KEY=open(os.path.join(D,"api-key.txt")).read().strip()
BASE=os.environ.get("QWEN_URL","http://127.0.0.1:8000")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--file", action="append", default=[], help="attach a file (repeatable)")
    ap.add_argument("--effort", default="xhigh", choices=["xhigh","medium","low","off"])
    ap.add_argument("--max-tokens", type=int, default=90000)
    ap.add_argument("--temp", type=float, default=None, help="override sampling temperature")
    ap.add_argument("--fast", action="store_true", help="use/boot the ninfer fast server (10-20s boot) when the main server is down")
    a=ap.parse_args()

    global BASE
    WINDOW = 106_000
    if a.fast:
        import subprocess
        def _up(url):
            try:
                h={"Authorization":"Bearer "+KEY} if KEY else {}
                urllib.request.urlopen(urllib.request.Request(url+"/v1/models",headers=h),timeout=3)
                return True
            except Exception: return False
        if _up("http://127.0.0.1:8080"):
            BASE="http://127.0.0.1:8080"; WINDOW=32_000
            print("(fast server already up)")
        elif _up("http://127.0.0.1:8000"):
            print("(main server already running -- using it, nothing to boot)")
        else:
            print("booting fast server (ninfer, ~10-20s)...")
            os.makedirs("/opt/ninfer/logs", exist_ok=True)
            subprocess.Popen(["/opt/ninfer/src/build/apps/ninfer-serve",
                "/opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer",
                "--max-context","32768","--kv-dtype","int8","--max-concurrency","2",
                "--spec","mtp","--draft-tokens","3","--lm-head-draft","--api-key",KEY],
                stdout=open("/opt/ninfer/logs/fast.out","ab"),
                stderr=open("/opt/ninfer/logs/fast.err","ab"))
            for _ in range(30):
                time.sleep(2)
                if _up("http://127.0.0.1:8080"): break
            else:
                print("!! fast server failed to start -- see /opt/ninfer/logs/fast.err"); sys.exit(1)
            BASE="http://127.0.0.1:8080"; WINDOW=32_000
            print("fast server READY (it stays up; stop with STOP-FAST.bat)")

    parts=[]
    for f in a.file:
        try:
            parts.append("### %s\n```\n%s\n```" % (os.path.basename(f),
                          open(f, encoding="utf-8", errors="replace").read()))
        except Exception as e:
            print("could not read %s: %s" % (f,e), file=sys.stderr); sys.exit(1)
    q=" ".join(a.question).strip()
    if not q and not parts:
        print("nothing to ask. give a question or --file", file=sys.stderr); sys.exit(1)
    prompt=("\n\n".join(parts)+"\n\n"+q).strip()

    body=dict(model="qwen3.8-27b",
              max_tokens=a.max_tokens, stream=True,
              # ask for real usage: counting stream deltas undercounts badly, and this build
              # does not reliably split reasoning_content in streaming mode
              stream_options={"include_usage": True},
              messages=[{"role":"user","content":prompt}])
    if a.effort == "off":
        # thinking disabled entirely -- a separate mechanism from reasoning_effort.
        # Qwen3.8 model card recommends DIFFERENT sampling for non-thinking mode:
        # temperature=0.7, top_p=0.80, presence_penalty=1.5 (vs 1.0/0.95 for thinking).
        if "8080" in BASE:
            body["reasoning_effort"] = "none"      # ninfer's documented off-switch
        else:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        body["temperature"] = a.temp if a.temp is not None else 0.7
        body["top_p"] = 0.80
        body["presence_penalty"] = 1.5
    else:
        body["reasoning_effort"] = a.effort
        body["temperature"] = a.temp if a.temp is not None else 1.0
        body["top_p"] = 0.95
    req=urllib.request.Request(BASE+"/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})

    # Pre-flight: the server enforces prompt + max_tokens <= 106,496 (measured exactly).
    # chars/3 over-estimates tokens for code, which errs on the safe side here.
    est_prompt = len(prompt) // 3 + 300
    if est_prompt + a.max_tokens > WINDOW:
        new_max = WINDOW - est_prompt
        if new_max < 2_000:
            print("!! attachment too large: ~%d tokens estimated; even a minimal answer" % est_prompt)
            print("!! budget will not fit this server's window. Trim the file and retry.")
            sys.exit(1)
        print("note: large prompt (~%d tokens est) -> lowering max_tokens %d -> %d to fit the window"
              % (est_prompt, a.max_tokens, new_max))
        a.max_tokens = new_max
        body["max_tokens"] = new_max
    print("effort=%s  max_tokens=%s  prompt~%d chars" % (a.effort, a.max_tokens, len(prompt)))
    print("(xhigh commonly runs 4-10 minutes; thinking is shown dimmed as it happens)\n")
    t0=time.time(); n=0; thinking=0; answering=False; last=t0; usage=None; first_tok=None
    try:
        resp = urllib.request.urlopen(req, timeout=3600)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try: detail = json.loads(detail)["error"]["message"]
        except Exception: pass
        print("\n!! request rejected (HTTP %s): %s" % (e.code, detail))
        if "maximum context length" in str(detail):
            print("   Prompt + max_tokens must fit in 106,496 total.")
            print("   Fix: shrink the attachment, or rerun with a lower --max-tokens.")
        sys.exit(1)
    except urllib.error.URLError as e:
        print("\n!! could not reach the server at %s (%s)" % (BASE, getattr(e, "reason", e)))
        print("   Is it running? Start it with START-QWEN.bat and wait for 'startup complete'.")
        sys.exit(1)
    with resp as r:
        for raw in r:
            line=raw.decode("utf-8","replace").strip()
            if not line.startswith("data: "): continue
            payload=line[6:]
            if payload=="[DONE]": break
            try: d=json.loads(payload)
            except Exception: continue
            if d.get("usage"): usage=d["usage"]
            ch=(d.get("choices") or [{}])
            delta=(ch[0].get("delta") or {}) if ch else {}
            rc=delta.get("reasoning_content")
            c=delta.get("content")
            if rc:
                thinking+=1; n+=1
                if time.time()-last>2.0:
                    print("\r  ...thinking (%d tokens, %ds)   " % (thinking, time.time()-t0),
                          end="", flush=True); last=time.time()
            if c:
                if first_tok is None: first_tok=time.time()-t0
                if not answering:
                    print("\r" + " "*50 + "\r", end="")
                    print("--- answer (after %d thinking tokens, %ds) ---\n" % (thinking, time.time()-t0))
                    answering=True
                n+=1; sys.stdout.write(c); sys.stdout.flush()
    dt=time.time()-t0
    if usage:
        out=usage.get("completion_tokens") or 0
        det=usage.get("completion_tokens_details") or {}
        rtok=det.get("reasoning_tokens")
        print("\n\n--- %d output tokens in %ds (%.0f tok/s) ---" % (out, dt, out/dt if dt else 0))
        if rtok: print("    %d of them thinking (%.0f%%)" % (rtok, 100.0*rtok/out))
        elif dt > 5 and not answering: pass
        else:
            print("    time to first answer token: %.0fs (that gap is the thinking)"
                  % (first_tok if first_tok else dt))
        print("    prompt %s tokens" % usage.get("prompt_tokens"))
    else:
        print("\n\n--- finished in %ds (no usage reported) ---" % dt)
    if not answering:
        print("!! NO ANSWER -- it spent the entire budget thinking.")
        print("!! rerun with --max-tokens %d, or --effort medium." % (a.max_tokens*2))

if __name__=="__main__":
    main()
