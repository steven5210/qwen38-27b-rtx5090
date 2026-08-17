# Qwen3.8-27B on a single RTX 5090 — a validated, one-click local setup

Runs **Qwen3.8-27B (unsloth NVFP4)** on **vLLM 0.27.1** under WSL2, tuned and measured on a
desktop RTX 5090 (SM120, 32GB). OpenAI-compatible API with thinking, tool calling, 80K context
(96K profile included), speculative decoding, and prefix caching.

Every flag in here exists because something broke without it. The battle log below is the real
value of this repo: nine problems that each cost hours, already solved.

**Measured on the reference machine** (Ryzen 9 5900X / 32GB RAM / RTX 5090):

| Scenario | Result |
|---|---|
| Short coding reply, thinking off | **112–117 tok/s**, first token ~0.15s |
| Decode with 10K context loaded | **124–126 tok/s** |
| Deep reasoning, large context | 20–55 tok/s (real envelope on hard work) |
| Prompt ingest, bare desktop | **~5,300 tok/s** (88K tokens in 19s) |
| Repeat turn with prefix cache | **0.39s** to first token (vs ~20s cold) |
| MTP draft acceptance | 90–99% on code, 40–60% on deep reasoning |
| Long-context accuracy | **8/8 exact needle retrieval at 88K** |

For comparison, the same hardware running the previous-gen Qwen3.6-27B (NVIDIA NVFP4 via Docker,
Marlin kernel path) peaked at 72–77 tok/s. This setup is ~1.5–1.6× faster on a newer model.

---

## Requirements

- RTX 5090 (or another 32GB Blackwell card), recent NVIDIA driver (610+)
- Windows 11 with WSL2 available, ~60GB free disk, 32GB system RAM
- No Docker needed. No Hugging Face account needed (the model is public).

## Setup (two double-clicks)

1. **`SETUP.bat`** — installs Ubuntu-26.04 under WSL2, sizes `.wslconfig`, installs the pinned
   Python/CUDA stack, fetches the official chat template, downloads the model (~20GB).
   Takes 15–40 minutes depending on your connection. Safe to re-run.
2. **`START-QWEN.bat`** — boots the server. ~5 minutes the first time (compiles kernels, cached
   afterward), ~2.5 minutes on later boots. Ready when the log shows `Application startup complete`.

Then point any OpenAI-compatible client at:

- **Base URL:** `http://127.0.0.1:8000/v1`
- **Model:** `qwen3.8-27b`
- **API key:** auto-generated on first run into `api-key.txt` (unique per machine; delete to rotate)

Stop with `STOP-QWEN.bat`. Closing the server window also stops it. It does **not** auto-start on
boot by design.

### Optional

- **`START-96K.bat`** — 96K context, single request slot. For whole-repo / huge-document sessions.
  Requires a bare desktop (see the VRAM rule below).
- **`REGISTER-MAINTENANCE.bat`** — daily 5am restart that only fires **if the server is already
  running**. Caps the slow memory growth of the experimental prefix cache. Remove with
  `schtasks /Delete /TN Qwen38Maintenance`.
- **`bench.py` / `bench2.py`** — the benchmark harnesses used to produce the numbers above.
  Run inside WSL: `/opt/qwen38/venv/bin/python bench.py --tag mytest`

## The one rule that matters: keep desktop VRAM low

The server takes ~29–30GB of the card. If desktop apps (Wallpaper Engine, Chrome with hardware
acceleration, games) hold more than roughly 1.3GB, Windows starts **paging GPU memory** and
throughput collapses by 10× — while everything still "works," so it reads as a mystery slowdown.

`serve-wsl.sh` measures desktop VRAM before loading the model and prints a loud `PREFLIGHT`
warning if you are over budget. Check `logs/serve.log` for that line whenever performance feels off.
To find the culprit: Task Manager → Details tab → add the **Dedicated GPU memory** column → sort.

## Client settings (Cline / Roo / Continue / any OpenAI client)

| Setting | Value | Why |
|---|---|---|
| Context Window Size | **70000** (80K profile) / 86000 (96K profile) | Client token estimators undercount Qwen's tokenizer; the margin prevents truncated turns |
| Max Output Tokens | **16384** | Thinking shares this budget — starving it truncates turns mid-tool-call |
| Temperature | **1.0, explicitly set** | Some clients send 0 by default; greedy decoding makes thinking models loop |
| Reasoning Effort | **medium** | Default is `xhigh` (maximum depth). See the effort section below |
| Auto-condense threshold | **~60%** | Compaction requests are LLM calls too; they fail if the conversation is already huge |

Anything you don't send (top_p / top_k / min_p) falls back to the checkpoint's recommended values
(0.95 / 20 / 0). The server never overrides client-sent values.

## reasoning_effort: the dial nobody mentions

Qwen3.8 supports `reasoning_effort` with levels **xhigh (default), medium, low** — plus thinking
off entirely via `chat_template_kwargs: {"enable_thinking": false}`. The mechanism is a single
instruction injected by the chat template (medium injects nothing — it's the model's natural depth).

Measured on one hard prompt with an 8K output budget:

| Effort | Time | Thinking | Outcome |
|---|---|---|---|
| xhigh (default) | 103s | 33,500 chars | **hit the cap, no answer produced** |
| medium | 55s | 9,900 chars | complete answer |
| low | 47s | 5,400 chars | complete answer |

The default being `xhigh` is why "it thinks forever" is the most common complaint about this model.
Use medium for agent work; save xhigh for genuinely hard one-off problems. Note that `low` can cost
more end-to-end in agent loops (faster turns, more retries) — this matches Qwen's own guidance.

This repo passes `--chat-template` with the **official** template (fetched during setup) because
the effort levels live in it.

---

## Battle log — nine problems, already solved

Each of these presents as something else entirely. If you deviate from the pinned setup, this is
your debugging map.

1. **Triton: "Failed to find C compiler"** — Ubuntu-26.04 ships without gcc.
   → `apt install build-essential`.
2. **MTP draft head: "Could not find nvcc"** — CUDA *runtime* wheels don't include the compiler.
   → `uv pip install nvidia-cuda-nvcc`.
3. **"CUDA compiler and toolkit headers are incompatible"** — nvcc 13.3 against torch's CUDA 13.2
   headers. → Pin nvcc to torch's version: `nvidia-cuda-nvcc==13.2.*` (setup does this automatically).
4. **`ptxas fatal: Unsupported .version 9.3`** while FlashInfer built CUTLASS FP4 kernels.
   → Skip local compilation with the prebuilt kernel cache:
   `flashinfer-jit-cache==<version> --extra-index-url https://flashinfer.ai/whl/cu130/` (1.4GB).
5. **Engine dies silently during warmup, no error** — WSL2 defaults to ~50% of host RAM; the parallel
   kernel compile gets OOM-killed. → Raise the WSL memory cap for first-time setup, then **lower it**
   (16GB) once caches are warm. A 26GB cap starves Windows on cold boots and freezes the desktop.
   Also cap `MAX_JOBS=4`.
6. **Decode collapses to ~10 tok/s under load** (fast after boot, dies later) — GPU memory
   oversubscription: vLLM's budget + desktop VRAM exceeds the card, Windows pages. → `util 0.89` and
   keep the desktop lean. This masqueraded as three different bugs before we caught it; always check
   `nvidia-smi` memory before blaming flags.
7. **Prefill stuck ~500 tok/s** — two causes: MTP caps the scheduler at 2,048 batched tokens, and
   piecewise-only CUDA graphs. → `--max-num-batched-tokens 12288` +
   `--compilation-config '{"cudagraph_mode": "FULL_AND_PIECEWISE"}'`. Result: ~1,650–5,300 tok/s.
8. **Every turn re-reads the whole conversation** — vLLM silently sets `enable_prefix_caching=False`
   on hybrid-Mamba models. → `--enable-prefix-caching --mamba-cache-mode align --prefix-match-unit 16`
   (vLLM PR #46384, merged July 2026). Repeat turns went from ~20s to 0.39s; hit rates reach 85–88%.
   Note this mode is experimental and its memory footprint grows over long sessions — hence the
   0.89 utilization and the optional nightly restart.
9. **`--default-chat-template-kwargs` wedges the whole server** — on vLLM 0.27.1 it accepts requests
   that then generate nothing, forever, with zero errors logged. → **Do not use it.** Configure
   per-client instead.

### Things that sound like optimizations but aren't (all tested here)

- **Speculative depth 2** (a popular recommendation): measurably worse. Depth 3 was 27% faster on
  single-stream work, 64% faster than depth 1. Keep `num_speculative_tokens: 3`.
- **A "fixed" community chat template**: the official template's empty `<think></think>` blocks for
  prior turns are correct, well-formed, and cost ~6 tokens per turn. Nothing to fix on vLLM.
- **bf16 KV cache for long-context quality**: fp8 scored 8/8 needle retrieval at both 40K and 88K.
  The reported degradation doesn't manifest here, and bf16 would halve your context.
- **Raising max-model-len past 80K on the 4-slot profile**: the KV pool *shrinks* as the window
  grows (workspace reservations scale with it). 80K → 111,264-token pool; 84K → 87,262; 88K fails
  to boot. The surplus at 80K is what powers prefix caching and concurrency.

## Profiles

| Profile | Context | Slots | Use |
|---|---|---|---|
| `START-QWEN.bat` (default) | 80K | 4 | Daily driver, tolerates a second user/agent |
| `START-96K.bat` | 96K | 1 | Max context, single user, bare desktop |
| `CTX=61440 UTIL=0.88 bash serve-wsl.sh` | 60K | 4 | Heavy desktop use (wallpaper engine, etc.) |

Every knob is an environment variable: `CTX`, `UTIL`, `SEQS`, `MNBT`, `SPEC_TOKENS`, `SPEC=0`,
`KERNEL_FALLBACK=1`.

## Remote access (optional)

The server binds `0.0.0.0` inside WSL, which WSL2's NAT keeps off your LAN by default. To reach it
from another machine, install Tailscale **inside WSL** (`curl -fsSL https://tailscale.com/install.sh | sh`
then `tailscale up --hostname=qwen-5090`) and use that node's tailnet IP — `serve-wsl.sh` keeps the
daemon alive automatically. Bearer auth is always on.

## Credits

Built and measured over three days against a real Cline workload. Model by Qwen, NVFP4 quant by
Unsloth, serving by vLLM.
