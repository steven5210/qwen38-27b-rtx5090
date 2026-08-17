#!/bin/bash
# setup-wsl.sh - one-time provisioning inside Ubuntu-26.04 WSL. Run via SETUP.bat.
set -e
echo "=== [1/5] base packages ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -y && apt-get install -y build-essential curl git
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.local/bin:$PATH"
echo "=== [2/5] python stack (pinned - these exact versions are load-bearing) ==="
mkdir -p /opt/qwen38
[ -d /opt/qwen38/venv ] || uv venv /opt/qwen38/venv --python 3.12
source /opt/qwen38/venv/bin/activate
uv pip install "vllm==0.27.1" "flashinfer-python>=0.6.13" "nvidia-cutlass-dsl>=4.5.2" hf_transfer huggingface_hub --torch-backend=auto
echo "=== [3/5] CUDA toolchain pins (see README battle log #2-#4) ==="
CUDAV=$(python -c "import torch; v=torch.version.cuda; print('.'.join(v.split('.')[:2]))")
uv pip install "nvidia-cuda-nvcc==${CUDAV}.*"
FIV=$(python -c "import flashinfer; print(flashinfer.__version__)")
uv pip install "flashinfer-jit-cache==${FIV}" --extra-index-url https://flashinfer.ai/whl/cu130/ || echo "jit-cache wheel unavailable; kernels will compile locally (slower first boot)"
echo "=== [4/5] official reasoning_effort-aware chat template ==="
curl -sL -m 60 "https://huggingface.co/Qwen/Qwen3.8-27B/raw/main/chat_template.jinja" -o /opt/qwen38/chat_template_official.jinja
grep -q reasoning_effort /opt/qwen38/chat_template_official.jinja && echo "template OK"
echo "=== [5/5] model download (~20GB, one-time) ==="
export HF_HUB_ENABLE_HF_TRANSFER=1
export HF_HOME=/opt/qwen38/hf
hf download unsloth/Qwen3.8-27B-NVFP4
echo "=== SETUP COMPLETE - run START-QWEN.bat ==="
