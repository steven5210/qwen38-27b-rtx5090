#!/bin/bash
# phase2b.sh -- Phase 2 battery at the FULL 252,928 window (patched ninfer, int8, MTP3, conc 2)
R=/mnt/c/Users/StevenPC/Downloads/qwen38
OUT=$R/logs/phase2b.log
PY=/opt/qwen38/venv/bin/python
AK=$(cat $R/api-key.txt)
NURL=http://127.0.0.1:8080/v1/chat/completions
b(){ echo; echo "########## $1 ##########"; date; }
{
b "R RETRO: cache= reuse stats mined from the Phase 2 server logs"
for f in /opt/ninfer/logs/p2.out /opt/ninfer/logs/p2.err /opt/ninfer/logs/mk.out /opt/ninfer/logs/mk.err; do
  [ -f "$f" ] && echo "$f: $(grep -aoE 'cache=[0-9]+' $f | wc -l) cache= lines"
done
echo "-- phase2 run:"
cat /opt/ninfer/logs/p2.out /opt/ninfer/logs/p2.err 2>/dev/null | grep -aoE 'cache=[0-9]+' | awk -F= '{n++; s+=$2; if($2>0)h++} END{printf "requests with cache>0: %d/%d, reused tokens total: %d\n",h,n,s}'
echo "-- makeup run (cold pass should be 0, hot pass >0 if reuse is real):"
cat /opt/ninfer/logs/mk.out /opt/ninfer/logs/mk.err 2>/dev/null | grep -aoE 'cache=[0-9]+' | awk -F= '{n++; s+=$2; if($2>0)h++} END{printf "requests with cache>0: %d/%d, reused tokens total: %d\n",h,n,s}'
echo "-- makeup per-request cache= sequence (order = cold 12 then hot 12):"
cat /opt/ninfer/logs/mk.out /opt/ninfer/logs/mk.err 2>/dev/null | grep -aoE 'cache=[0-9]+' | tr '\n' ' '; echo

b "0 SWAP: vLLM idle-wait -> patched ninfer @ 252,928 (int8, conc 2, MTP3, JSONL on)"
for i in $(seq 1 24); do
  RUN=$(curl -s -m 3 http://127.0.0.1:8000/metrics -H "Authorization: Bearer $AK" | grep -a "^vllm:num_requests_running" | awk '{s+=$2} END{print int(s)}')
  [ "${RUN:-0}" = "0" ] && break; sleep 10
done
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 8
: > /opt/ninfer/logs/p2b.jsonl
T0=$(date +%s)
nohup /opt/ninfer/src/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
  --api-key "$AK" --max-context 252928 --kv-dtype int8 --max-concurrency 2 \
  --spec mtp --draft-tokens 3 --lm-head-draft \
  --request-log-jsonl /opt/ninfer/logs/p2b.jsonl > /opt/ninfer/logs/p2b.out 2> /opt/ninfer/logs/p2b.err &
for i in $(seq 1 60); do sleep 3; curl -s -m 3 -o /dev/null -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models && break; done
echo "boot seconds: $(( $(date +%s) - T0 ))"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
git -C /opt/ninfer/src log --oneline -1

b "1 FULL CODEEVAL, medium, samples=3 (106K-run scores: 24/24, 3/3, 2/2)"
cd $R && EVAL_URL=$NURL EVAL_EFFORT=medium $PY -u codeeval.py --tag P2B --samples 3 2>&1 | tail -20

b "2 NEEDLES at 96K / 173K / 236K (bake-off was 3/3)"
cd $R && TARGET_URL=$NURL NEEDLE_SIZES=96000,173000,236000 $PY -u needleprobe.py 2>&1

b "3 CONCURRENCY-2 WITH TWO ~100K PROMPTS (admission + parallel prefill)"
cd $R && TARGET_URL=$NURL $PY -u conc2big.py 2>&1
nvidia-smi --query-gpu=memory.used --format=csv,noheader

b "4 ENDURANCE 22 min, larger context mix incl. 100K/150K"
cd $R && TARGET_URL=$NURL DURATION_MIN=22 CTX_SIZES=1000,8000,20000,60000,100000,150000 $PY -u endure.py 2>&1 | tail -28

b "5 CLINESIM vs NINFER (sequential + interleaved TTFT)"
cd $R && TARGET_URL=http://127.0.0.1:8080 TURNS=8 CHUNK_TOKENS=8000 $PY -u clinesim.py 2>&1

b "6 FORENSICS: p2b JSONL + cache= lines from this run"
JSONL_PATH=/opt/ninfer/logs/p2b.jsonl $PY -u $R/jsonlpeek.py 2>&1 | grep -v "first record"
cat /opt/ninfer/logs/p2b.out /opt/ninfer/logs/p2b.err 2>/dev/null | grep -aoE 'cache=[0-9]+' | awk -F= '{n++; s+=$2; if($2>0)h++} END{printf "p2b requests with cache>0: %d/%d, reused tokens total: %d\n",h,n,s}'

b "7 RESTORE PRODUCTION vLLM"
pkill -9 -f ninfer-serve; sleep 8
nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
echo "health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"

b "8 CLINESIM vs PRODUCTION vLLM (same test, same sizes)"
cd $R && TARGET_URL=http://127.0.0.1:8000 TURNS=8 CHUNK_TOKENS=8000 $PY -u clinesim.py 2>&1

b "PHASE 2B COMPLETE"
echo PHASE2B_DONE
} > $OUT 2>&1
