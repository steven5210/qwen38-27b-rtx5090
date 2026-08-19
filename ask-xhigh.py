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
import argparse, json, os, sys, time, urllib.request
D=os.path.dirname(os.path.abspath(__file__))
KEY=open(os.path.join(D,"api-key.txt")).read().strip()
BASE=os.environ.get("QWEN_URL","http://127.0.0.1:8000")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--file", action="append", default=[], help="attach a file (repeatable)")
    ap.add_argument("--effort", default="xhigh", choices=["xhigh","medium","low"])
    ap.add_argument("--max-tokens", type=int, default=90000)
    ap.add_argument("--temp", type=float, default=1.0)
    a=ap.parse_args()

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

    body=dict(model="qwen3.8-27b", temperature=a.temp, top_p=0.95,
              max_tokens=a.max_tokens, reasoning_effort=a.effort, stream=True,
              # ask for real usage: counting stream deltas undercounts badly, and this build
              # does not reliably split reasoning_content in streaming mode
              stream_options={"include_usage": True},
              messages=[{"role":"user","content":prompt}])
    req=urllib.request.Request(BASE+"/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})

    print("effort=%s  max_tokens=%s  prompt~%d chars" % (a.effort, a.max_tokens, len(prompt)))
    print("(xhigh commonly runs 4-10 minutes; thinking is shown dimmed as it happens)\n")
    t0=time.time(); n=0; thinking=0; answering=False; last=t0; usage=None; first_tok=None
    with urllib.request.urlopen(req, timeout=3600) as r:
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
