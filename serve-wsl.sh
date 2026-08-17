#!/bin/bash
# serve-wsl.sh - Qwen3.8-27B (unsloth NVFP4) on vLLM 0.27.1, tuned for RTX 5090 32GB (SM120).
# Portable: locates its own folder; run through the START-*.bat launchers.
BASE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$BASE/logs"
exec > "$BASE/logs/serve.log" 2>&1
set -x
source /opt/qwen38/venv/bin/activate
export HF_HOME=/opt/qwen38/hf
export VLLM_ENGINE_READY_TIMEOUT_S=1800
export MAX_JOBS="${MAX_JOBS:-4}"
export NVCC_THREADS=2
export CUDA_HOME=/opt/qwen38/venv/lib/python3.12/site-packages/nvidia/cu13
export PATH="$CUDA_HOME/bin:$PATH"
export VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR=/opt/qwen38/cache/flashinfer_autotune
export TRITON_CACHE_DIR=/opt/qwen38/cache/triton
mkdir -p /opt/qwen38/cache/flashinfer_autotune /opt/qwen38/cache/triton
# optional tailscale (no-op if not installed)
if command -v tailscaled >/dev/null 2>&1; then
  if [ "$(ps -p 1 -o comm=)" = "systemd" ]; then systemctl start tailscaled 2>/dev/null || true
  else pgrep -x tailscaled >/dev/null || { setsid tailscaled > /var/log/tailscaled.log 2>&1 & sleep 2; }
  fi
fi
# API key: auto-generated per machine on first run (delete api-key.txt to rotate)
if [ ! -f "$BASE/api-key.txt" ]; then
  echo -n "sk-qwen38-$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32)" > "$BASE/api-key.txt"
  echo "Generated new API key -> $BASE/api-key.txt"
fi
cp -f "$BASE/api-key.txt" /opt/qwen38/api-key.txt
API_KEY=$(cat /opt/qwen38/api-key.txt)
# VRAM preflight: at this point vllm is not loaded, so GPU usage = desktop apps.
DESKTOP_MB=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -d ' ')
echo "=== PREFLIGHT: desktop VRAM = ${DESKTOP_MB} MiB ==="
if [ "${DESKTOP_MB:-0}" -gt 1300 ]; then
  echo "!!! WARNING: desktop apps hold ${DESKTOP_MB} MiB VRAM. This profile wants <= ~1300 MiB or"
  echo "!!! Windows pages GPU memory and speed collapses. Close Wallpaper Engine / Chrome / games."
  sleep 10
fi
CTX="${CTX:-81920}"
UTIL="${UTIL:-0.89}"
SEQS="${SEQS:-4}"
SPEC="${SPEC:-1}"
SPEC_TOKENS="${SPEC_TOKENS:-3}"
KERNEL_FALLBACK="${KERNEL_FALLBACK:-0}"
ARGS=( serve unsloth/Qwen3.8-27B-NVFP4
  --served-model-name qwen3.8-27b
  --host 0.0.0.0 --port 8000
  --api-key "$API_KEY"
  --max-model-len "$CTX"
  --kv-cache-dtype fp8_e4m3
  --gpu-memory-utilization "$UTIL"
  --max-num-seqs "$SEQS"
  --max-num-batched-tokens "${MNBT:-12288}"
  --language-model-only
  --async-scheduling
  --compilation-config '{"cudagraph_mode": "FULL_AND_PIECEWISE"}'
  --enable-prefix-caching
  --mamba-cache-mode align
  --prefix-match-unit 16
  --chat-template /opt/qwen38/chat_template_official.jinja
  --reasoning-parser qwen3
  --enable-auto-tool-choice --tool-call-parser qwen3_coder )
if [ "$SPEC" = "1" ]; then ARGS+=( --speculative-config "{\"method\": \"mtp\", \"num_speculative_tokens\": ${SPEC_TOKENS}}" ); fi
if [ "$KERNEL_FALLBACK" = "1" ]; then ARGS+=( --kernel-config '{"enable_flashinfer_autotune": false}' ); fi
echo "=== SERVE LAUNCH $(date) ctx=$CTX util=$UTIL seqs=$SEQS spec=$SPEC_TOKENS ==="
exec vllm "${ARGS[@]}"
