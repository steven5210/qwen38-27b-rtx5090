#!/bin/bash
# phase2.sh -- full production-parity battery on the PATCHED ninfer build.
R=/mnt/c/Users/StevenPC/Downloads/qwen38
OUT=$R/logs/phase2.log
PY=/opt/qwen38/venv/bin/python
AK=$(cat $R/api-key.txt)
NURL=http://127.0.0.1:8080/v1/chat/completions
b(){ echo; echo "########## $1 ##########"; date; }
{
b "0 SWAP: vLLM idle-wait -> patched ninfer (int8, 106496 ctx, conc 2, JSONL on)"
for i in $(seq 1 24); do
  RUN=$(curl -s -m 3 http://127.0.0.1:8000/metrics -H "Authorization: Bearer $AK" | grep -a "^vllm:num_requests_running" | awk '{s+=$2} END{print int(s)}')
  [ "${RUN:-0}" = "0" ] && break; sleep 10
done
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 8
: > /opt/ninfer/logs/p2.jsonl
nohup /opt/ninfer/src/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
  --api-key "$AK" --max-context 106496 --kv-dtype int8 --max-concurrency 2 \
  --spec mtp --draft-tokens 3 --lm-head-draft \
  --request-log-jsonl /opt/ninfer/logs/p2.jsonl > /opt/ninfer/logs/p2.out 2> /opt/ninfer/logs/p2.err &
for i in $(seq 1 40); do sleep 3; curl -s -m 3 -o /dev/null -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models && break; done
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
git -C /opt/ninfer/src log --oneline -1

b "1 FULL CODEEVAL, medium, samples=3 (vLLM baseline: 24/24, 3/3, 2/2)"
cd $R && EVAL_URL=$NURL EVAL_EFFORT=medium $PY -u codeeval.py --tag P2NINFER --samples 3 2>&1 | tail -20

b "2 EFFORT MATRIX on their template resolution"
$PY - <<'PYX'
import json,time,urllib.request
AK=open('/mnt/c/Users/StevenPC/Downloads/qwen38/api-key.txt').read().strip()
def call(mx,eff,prompt,extra=None):
    body=dict(model="qwen3.8-27b",max_tokens=mx,temperature=1.0,
              messages=[{"role":"user","content":prompt}])
    if eff: body["reasoning_effort"]=eff
    if extra: body.update(extra)
    req=urllib.request.Request("http://127.0.0.1:8080/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+AK})
    t0=time.time(); r=json.load(urllib.request.urlopen(req,timeout=900)); dt=time.time()-t0
    u=r["usage"]; ch=r["choices"][0]
    return dt,u["completion_tokens"],ch.get("finish_reason"),len(ch["message"].get("content") or "")
EASY="What does HTTP 404 mean? One sentence."
HARD=("Implement an LRU cache with per-key TTL in Python: get/put/__len__, O(1) amortised, "
      "expired keys must not count toward capacity. Code only.")
for eff in ("none","low","medium","xhigh"):
    dt,out,fin,alen=call(300 if eff=="none" else 16384,eff,EASY if eff=="none" else HARD)
    print("effort=%-6s wall=%6.1fs out=%-6d finish=%-10s answer_chars=%d"%(eff,dt,out,fin,alen),flush=True)
PYX

b "3 STREAMING TOOL CALLS (Cline mode, patched content-as-string)"
cd $R && TARGET_URL=$NURL $PY -u streamtool.py 2>&1

b "4 MULTI-TURN TOOL REPLAY"
cd $R && TARGET_URL=$NURL $PY -u multiturn.py 2>&1

b "5 CONCURRENCY = 2"
$PY - <<'PYX'
import json,time,threading,urllib.request
AK=open('/mnt/c/Users/StevenPC/Downloads/qwen38/api-key.txt').read().strip()
res=[]
def one(i):
    body=dict(model="qwen3.8-27b",max_tokens=1200,temperature=1.0,reasoning_effort="medium",
              messages=[{"role":"user","content":"Write a detailed docstring-rich Python class for a rate limiter. v%d"%i}])
    req=urllib.request.Request("http://127.0.0.1:8080/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+AK})
    t0=time.time(); r=json.load(urllib.request.urlopen(req,timeout=600)); dt=time.time()-t0
    res.append((r["usage"]["completion_tokens"],dt))
t0=time.time()
ts=[threading.Thread(target=one,args=(i,)) for i in range(2)]
[t.start() for t in ts]; [t.join() for t in ts]
wall=time.time()-t0; tot=sum(o for o,_ in res)
print("streams:", [("%d tok in %.1fs -> %.1f tok/s"%(o,d,o/d)) for o,d in res])
print("aggregate: %d tokens in %.1fs = %.1f tok/s"%(tot,wall,tot/wall))
PYX

b "6 CACHE-HIT-PATH ACCURACY (their checkpoint system; vLLM baseline 18/18 both passes)"
cd $R && QWEN_URL=http://127.0.0.1:8080 $PY -u cachehit-eval.py --samples 2 --effort medium --tag p2ninfer 2>&1 | tail -12

b "7 ENDURANCE ~22 min varied load (vLLM stock config collapsed 27x here)"
cd $R && TARGET_URL=$NURL DURATION_MIN=22 $PY -u endure.py 2>&1 | tail -22

b "8 THEIR JSONL FORENSICS (reuse paths + speculative aggregate)"
$PY - <<'PYX'
import json
paths={}; acc=drf=0; n=0
for line in open("/opt/ninfer/logs/p2.jsonl"):
    try: d=json.loads(line)
    except Exception: continue
    if d.get("event")!="request_done": continue
    n+=1
    p=d.get("prefix_reuse_path") or d.get("metrics",{}).get("prefix_reuse_path") or "?"
    paths[p]=paths.get(p,0)+1
    sp=d.get("speculative") or d.get("timings_seconds",{}).get("speculative") or {}
    acc+=sp.get("accepted_tokens",0) or 0; drf+=sp.get("drafted_tokens",0) or 0
print("request_done events:",n)
print("reuse paths:",paths)
print("speculative acceptance: %.1f%% (%d/%d)"%((100.0*acc/drf) if drf else 0,acc,drf))
PYX

b "9 RESTORE PRODUCTION vLLM"
pkill -9 -f ninfer-serve; sleep 8
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 5
nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 16000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
echo "health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
b "PHASE 2 COMPLETE"
echo PHASE2_DONE
} > $OUT 2>&1
