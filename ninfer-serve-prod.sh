#!/bin/bash
# Production ninfer boot -- flags validated by the Phase 1/2/2b/2c/2d batteries.
R=/mnt/c/Users/StevenPC/Downloads/qwen38
AK=$(cat $R/api-key.txt)
source $R/ninfer-prod.conf
VFLAG=""; [ "${VISION:-0}" = "1" ] && VFLAG="--vision"
bash $R/killall-vllm.sh >/dev/null 2>&1
pkill -9 -f ninfer-serve 2>/dev/null; sleep 3
mkdir -p /opt/ninfer/logs
: > /opt/ninfer/logs/prod.err
echo "[ninfer] booting Qwen3.8-27B NVFP4  ctx=$CTX  int8 KV  MTP-3  conc 2  vision=${VISION:-0}"
echo "[ninfer] endpoint http://127.0.0.1:8080/v1  (boot takes ~10 seconds)"
exec /opt/ninfer/src/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
  --api-key "$AK" --max-context $CTX --kv-dtype int8 --max-concurrency 2 \
  --spec mtp --draft-tokens 3 --lm-head-draft $VFLAG \
  --request-log-jsonl /opt/ninfer/logs/prod.jsonl \
  2> >(tee -a /opt/ninfer/logs/prod.err >&2)
