#!/bin/bash
# phase2d.sh -- IMAGE + VIDEO head-to-head with the new LARGE-FONT clip.
R=/mnt/c/Users/StevenPC/Downloads/qwen38
OUT=$R/logs/phase2d.log
PY=/opt/qwen38/venv/bin/python
AK=$(cat $R/api-key.txt)
b(){ echo; echo "########## $1 ##########"; date; }
{
b "0 REGENERATE test clip with large font"
$PY -u $R/genvid2.py 2>&1

b "1 SWAP: vLLM idle-wait -> ninfer --vision @ 106,496"
for i in $(seq 1 24); do
  RUN=$(curl -s -m 3 http://127.0.0.1:8000/metrics -H "Authorization: Bearer $AK" | grep -a "^vllm:num_requests_running" | awk '{s+=$2} END{print int(s)}')
  [ "${RUN:-0}" = "0" ] && break; sleep 10
done
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 8
nohup /opt/ninfer/src/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
  --api-key "$AK" --max-context 106496 --kv-dtype int8 --max-concurrency 2 \
  --spec mtp --draft-tokens 3 --lm-head-draft --vision \
  > /opt/ninfer/logs/p2d.out 2> /opt/ninfer/logs/p2d.err &
UP=0
for i in $(seq 1 60); do sleep 3; curl -s -m 3 -o /dev/null -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models && { UP=1; break; }; done
echo "up=$UP"; nvidia-smi --query-gpu=memory.used --format=csv,noheader
if [ "$UP" = "1" ]; then
  b "2 ninfer: IMAGE probe + VIDEO probe (large-font clip, x2)"
  cd $R && QWEN_URL=http://127.0.0.1:8080 $PY -u vision-probe.py 2>&1
  cd $R && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions VID_B64=/opt/ninfer/testvid2.b64 VID_CODES=/opt/ninfer/testvid2.codes $PY -u vidprobe.py 2>&1
  cd $R && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions VID_B64=/opt/ninfer/testvid2.b64 VID_CODES=/opt/ninfer/testvid2.codes $PY -u vidprobe.py 2>&1
else
  echo "NINFER --vision BOOT FAILED; stderr tail:"; tail -c 2000 /opt/ninfer/logs/p2d.err
fi
b "3 SWAP: ninfer -> vLLM VISION=1"
pkill -9 -f ninfer-serve; sleep 8
VISION=1 nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
b "4 vLLM: IMAGE probe + VIDEO probe (same clip, x2)"
cd $R && QWEN_URL=http://127.0.0.1:8000 $PY -u vision-probe.py 2>&1
cd $R && TARGET_URL=http://127.0.0.1:8000/v1/chat/completions VID_B64=/opt/ninfer/testvid2.b64 VID_CODES=/opt/ninfer/testvid2.codes $PY -u vidprobe.py 2>&1
cd $R && TARGET_URL=http://127.0.0.1:8000/v1/chat/completions VID_B64=/opt/ninfer/testvid2.b64 VID_CODES=/opt/ninfer/testvid2.codes $PY -u vidprobe.py 2>&1
b "5 RESTORE plain production vLLM"
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 8
nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
echo "health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
b "PHASE 2D COMPLETE"
echo PHASE2D_DONE
} > $OUT 2>&1
