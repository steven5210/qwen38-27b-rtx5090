#!/bin/bash
# phase2c.sh -- IMAGE head-to-head: ninfer --vision vs vLLM VISION=1, both at 106,496.
R=/mnt/c/Users/StevenPC/Downloads/qwen38
OUT=$R/logs/phase2c.log
PY=/opt/qwen38/venv/bin/python
AK=$(cat $R/api-key.txt)
b(){ echo; echo "########## $1 ##########"; date; }
{
b "0 SWAP: vLLM idle-wait -> ninfer --vision @ 106,496 (int8, conc 2, MTP3)"
for i in $(seq 1 24); do
  RUN=$(curl -s -m 3 http://127.0.0.1:8000/metrics -H "Authorization: Bearer $AK" | grep -a "^vllm:num_requests_running" | awk '{s+=$2} END{print int(s)}')
  [ "${RUN:-0}" = "0" ] && break; sleep 10
done
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 8
T0=$(date +%s)
nohup /opt/ninfer/src/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
  --api-key "$AK" --max-context 106496 --kv-dtype int8 --max-concurrency 2 \
  --spec mtp --draft-tokens 3 --lm-head-draft --vision \
  > /opt/ninfer/logs/p2c.out 2> /opt/ninfer/logs/p2c.err &
UP=0
for i in $(seq 1 60); do sleep 3; curl -s -m 3 -o /dev/null -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models && { UP=1; break; }; done
echo "boot seconds: $(( $(date +%s) - T0 ))  up=$UP  (text-only boot was 26,684 MiB)"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
if [ "$UP" = "1" ]; then
  b "1 VISION PROBE vs ninfer (x2)"
  cd $R && QWEN_URL=http://127.0.0.1:8080 $PY -u vision-probe.py 2>&1
  cd $R && QWEN_URL=http://127.0.0.1:8080 $PY -u vision-probe.py 2>&1
  b "2 TEXT SANITY while --vision is on (1 hard prompt, medium)"
  $PY - <<'PYX'
import json,time,urllib.request
AK=open('/mnt/c/Users/StevenPC/Downloads/qwen38/api-key.txt').read().strip()
body=dict(model="qwen3.8-27b",max_tokens=16384,temperature=1.0,reasoning_effort="medium",
  messages=[{"role":"user","content":"Implement an LRU cache with per-key TTL in Python: get/put/__len__, O(1) amortised, expired keys must not count toward capacity. Code only."}])
req=urllib.request.Request("http://127.0.0.1:8080/v1/chat/completions",data=json.dumps(body).encode(),
  headers={"Content-Type":"application/json","Authorization":"Bearer "+AK})
t0=time.time(); r=json.load(urllib.request.urlopen(req,timeout=900)); dt=time.time()-t0
u=r["usage"]; c=r["choices"][0]["message"].get("content") or ""
print("text-during-vision: wall=%.1fs out=%d tok  has_class_def=%s"%(dt,u["completion_tokens"],"class" in c))
PYX
else
  echo "NINFER --vision BOOT FAILED; stderr tail:"; tail -c 2000 /opt/ninfer/logs/p2c.err
fi
b "3 SWAP: ninfer -> vLLM VISION=1"
pkill -9 -f ninfer-serve; sleep 8
T0=$(date +%s)
VISION=1 nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
echo "boot seconds: $(( $(date +%s) - T0 ))"
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
b "4 VISION PROBE vs vLLM VISION=1 (x2)"
cd $R && QWEN_URL=http://127.0.0.1:8000 $PY -u vision-probe.py 2>&1
cd $R && QWEN_URL=http://127.0.0.1:8000 $PY -u vision-probe.py 2>&1
b "5 RESTORE plain production vLLM"
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 8
nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
echo "health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
b "PHASE 2C COMPLETE"
echo PHASE2C_DONE
} > $OUT 2>&1
