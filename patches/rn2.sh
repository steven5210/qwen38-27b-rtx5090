#!/bin/bash
# rn2.sh -- residency-N live validation on the worktree binary; restores production at the end.
M=/mnt/c/Users/StevenPC/Downloads/qwen38
AK=$(cat $M/api-key.txt)
PY=/opt/qwen38/venv/bin/python
{
echo "=== RN2 residency validation $(date) ==="
pkill -9 -x ninfer-serve; sleep 4
: > /opt/ninfer/logs/rnval.jsonl
nohup /opt/ninfer/rn/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
  --host 0.0.0.0 --api-key "$AK" --max-context 252928 --kv-dtype int8 --max-concurrency 2 \
  --spec mtp --draft-tokens 3 --lm-head-draft \
  --request-log-jsonl /opt/ninfer/logs/rnval.jsonl > /opt/ninfer/logs/rnval.err 2>&1 &
C=000
for i in $(seq 1 40); do sleep 2; C=$(curl -s -m 3 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models); [ "$C" = "200" ] && break; done
echo "worktree server: HTTP $C  vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
if [ "$C" != "200" ]; then echo RN2_ABORT_BOOT; tail -5 /opt/ninfer/logs/rnval.err; exit 1; fi

echo; echo "--- [1/6] INTERLEAVE clinesim (the money test; was 7.5s late-turn TTFT):"
cd $M && TARGET_URL=http://127.0.0.1:8080 MODE=interleave TURNS=8 $PY clinesim.py 2>&1 | tail -14

echo; echo "--- [2/6] SEQ clinesim (baseline; was 4.1s late-turn TTFT):"
cd $M && TARGET_URL=http://127.0.0.1:8080 MODE=seq TURNS=8 $PY clinesim.py 2>&1 | tail -10

echo; echo "--- [3/6] toolab (require 20/20):"
cd $M && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions $PY toolab.py 2>&1 | tail -3

echo; echo "--- [4/6] streamtool + multiturn:"
cd $M && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions $PY streamtool.py 2>&1 | tail -2
cd $M && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions $PY multiturn.py 2>&1 | tail -2

echo; echo "--- [5/6] cachehit-eval (reuse accuracy):"
cd $M && QWEN_URL=http://127.0.0.1:8080 $PY cachehit-eval.py 2>&1 | tail -8

echo; echo "--- [6/6] JSONL forensics (per-request reuse; both conversations should append after turn 1):"
python3 $M/rnval_jsonl.py 2>&1 | head -60

echo; echo "--- restore production ninfer:"
pkill -9 -x ninfer-serve; sleep 4
nohup bash $M/ninfer-serve-prod.sh >/dev/null 2>&1 &
for i in $(seq 1 40); do sleep 2; C=$(curl -s -m 3 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models); [ "$C" = "200" ] && break; done
echo "production restored: HTTP $C  vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
echo RN2_DONE
} > $M/logs/rn2.log 2>&1
