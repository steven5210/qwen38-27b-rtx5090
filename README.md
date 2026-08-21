# Qwen3.8-27B on a single RTX 5090 — a validated, one-click local setup

Runs **Qwen3.8-27B (unsloth NVFP4)** two ways on a desktop RTX 5090 (SM120, 32GB) under WSL2 —
every number in this repo measured on this machine, nothing assumed:

- **Production: [ninfer](https://github.com/Neroued/ninfer)** — a from-scratch C++/CUDA engine
  running our four-commit fix branch. **252,928-token context** (2.4x the vLLM setup), ~10 s
  boots, live Cline turn starts of **150–565 ms** at 50–100K context, two conversations
  resident at once. Parts I–III.
- **Fallback: vLLM 0.27.1** — the original stack this repo was built on, still one click away
  (`STOP-NINFER.bat` restores it). 104K context, fully tuned and documented. Part IV.

Every flag in here exists because something broke without it. The battle log is the real value
of this repo: a dozen-plus problems that each cost hours, already solved — including one that
makes a server *silently* 27x slower after a few minutes of use, with no error anywhere.

## Table of contents

- [Quick reference](#quick-reference)
- [Part I — ninfer in production](#part-i--ninfer-in-production)
  - [Running it for real: the Phase-3 kit](#running-it-for-real-the-phase-3-kit)
  - [Cline settings on ninfer — both profiles](#cline-settings-on-ninfer--both-profiles)
  - [Remote access (optional)](#remote-access-optional)
  - [First live Cline session on ninfer (xhigh) — measured minutes in](#first-live-cline-session-on-ninfer-xhigh--measured-minutes-in)
  - [Residency-N: two conversations resident at once (validated, adopted)](#residency-n-two-conversations-resident-at-once-validated-adopted)
- [Part II — Setting up ninfer from scratch (humans and AI agents)](#part-ii--setting-up-ninfer-from-scratch-humans-and-ai-agents)
  - [Requirements (verified)](#requirements-verified)
  - [Step by step](#step-by-step)
  - [Cline settings (validated optima)](#cline-settings-validated-optima)
  - [Troubleshooting (every entry actually happened here)](#troubleshooting-every-entry-actually-happened-here)
  - [Hand this to an AI agent (copy-paste runbook)](#hand-this-to-an-ai-agent-copy-paste-runbook)
- [Part III — The bake-off and the fix branch](#part-iii--the-bake-off-and-the-fix-branch)
  - [The ninfer bake-off (same model, same card, a from-scratch C++ engine)](#the-ninfer-bake-off-same-model-same-card-a-from-scratch-c-engine)
- [Part IV — The vLLM stack (validated fallback)](#part-iv--the-vllm-stack-validated-fallback)
  - [Measured performance](#measured-performance)
  - [Requirements](#requirements)
  - [Setup (two double-clicks)](#setup-two-double-clicks)
  - [Client settings (Cline / Roo / Continue / any OpenAI client)](#client-settings-cline--roo--continue--any-openai-client)
  - [The cap is prompt + output, not prompt](#the-cap-is-prompt--output-not-prompt)
  - [The locked configuration, and why every flag is there](#the-locked-configuration-and-why-every-flag-is-there)
  - [Profiles](#profiles)
  - [The one rule that matters: keep desktop VRAM low](#the-one-rule-that-matters-keep-desktop-vram-low)
  - [The silent 27x slowdown — root cause and fix](#the-silent-27x-slowdown--root-cause-and-fix)
  - [Pin the KV pool, don't let vLLM guess](#pin-the-kv-pool-dont-let-vllm-guess)
  - [reasoning_effort: the dial nobody mentions](#reasoning_effort-the-dial-nobody-mentions)
  - [Do NOT use reasoning_effort xhigh for agent coding](#do-not-use-reasoning_effort-xhigh-for-agent-coding)
  - [How much room does xhigh actually need? (and why no setting fixes it)](#how-much-room-does-xhigh-actually-need-and-why-no-setting-fixes-it)
  - [MTP speculative decoding: what acceptance actually looks like](#mtp-speculative-decoding-what-acceptance-actually-looks-like)
  - [Vision: what it actually costs (measured, 3 boots)](#vision-what-it-actually-costs-measured-3-boots)
  - [Is prefix caching safe here? (vLLM #47861)](#is-prefix-caching-safe-here-vllm-47861)
  - [Accuracy validation](#accuracy-validation)
  - [Battle log — setup problems, already solved](#battle-log--setup-problems-already-solved)
  - [Things that sound like optimizations but aren't (all tested here)](#things-that-sound-like-optimizations-but-arent-all-tested-here)
- [Credits](#credits)


## Quick reference

If you read nothing else, read this. Every value is measured; the linked sections explain why.

**Cline settings — ninfer (production)**

| Setting | daily driver (medium) | full capability (xhigh) |
|---|---|---|
| Base URL | `http://127.0.0.1:8080/v1` (remote: your Tailscale IP) | same |
| Model / API key | `qwen3.8-27b` / from `api-key.txt` | same |
| **Context Window Size** | **252,928** (vision profile: 152,576) | 252,928 |
| **Max Output Tokens** | **32,768** | **131,072** |
| **Reasoning Effort** | **medium** | xhigh |
| **Temperature** | **1.0, set explicitly** — clients that send 0 make thinking models loop | same |

Server profiles live in `ninfer-prod.conf`: Option B text-max `CTX=252928 VISION=0` (default)
or Option A vision `CTX=152576 VISION=1`. vLLM fallback client settings (`:8000`, window
96,000, output 16,384): see [Client settings](#client-settings-cline--roo--continue--any-openai-client).

**Commands**

| | |
|---|---|
| **`START-NINFER.bat`** | **production server — READY in ~10 s, NMON dashboard auto-opens** |
| `STOP-NINFER.bat` | stop ninfer and restore the vLLM fallback stack |
| `STOP-ALL.bat` | stop *everything*, restore nothing (the heavy-system-job button) |
| `START-QWEN.bat` / `STOP-QWEN.bat` | vLLM fallback daily driver (MONITOR.bat auto-opens) |
| **`QWEN-ASK.bat`** | ask a question — menu of presets; option 7 = 10-second ninfer FAST path |
| `ASK-MEDIUM.bat` / `ASK-XHIGH.bat` | the same without the menu, for scripting |
| `ASK-FAST.bat` / `STOP-FAST.bat` | one-off ninfer ask when nothing else is running |
| `START-VISION.bat` / `START-SHARED.bat` | vLLM vision profile / two people at 60K |

**The four things that will bite you**

1. **Desktop VRAM over ~1.3GB** → Windows pages GPU memory, 10x slowdown, no error. Close
   Wallpaper Engine. (Both stacks.)
2. **Reasoning effort left unset** → the chat template defaults to `xhigh`, which scored
   **9/24 vs medium's 24/24** for agent coding here. [Details](#do-not-use-reasoning_effort-xhigh-for-agent-coding). (Both stacks.)
3. **`VISION=1` with `CTX` above 152,576 on ninfer** → boots fine, then prefill runs 11x
   slower with flaky image answers. Use the profile pair as written.
4. **Raising `--max-num-batched-tokens` on vLLM** → looks like a prefill optimization,
   silently makes the server 27x slower after ten minutes.

---

## Part I — ninfer in production

The engine this machine runs today, with the four-commit fix branch adopted and validated.
Boot it, point Cline at it, done.

### Running it for real: the Phase-3 kit

`START-NINFER.bat` boots the validated production profile in ~10 seconds (config in
`ninfer-prod.conf`, monitor window auto-opens via `nmon.py` — READY state, VRAM alarms,
reuse tallies, throughput). `STOP-NINFER.bat` is one click back to the vLLM stack (via `stop-ninfer.sh`). The kit boots
with `--host 0.0.0.0` (API-key gated): Tailscale lives *inside* WSL here, and ninfer's default
is loopback-only — the one connectivity difference from vLLM's `--host 0.0.0.0` that bites
remote clients. `STOP-ALL.bat` stops *everything* — ninfer, vLLM, stray builds — and
restarts nothing, printing an empty-port list + GPU memory as proof (the button you want when
a heavy system job needs the whole machine).
Cline settings against ninfer: OpenAI Compatible, base URL `http://127.0.0.1:8080/v1`,
model `qwen3.8-27b`, context window **252,928**, max output **32,768** → **~220K usable
prompt, 2.4x the vLLM setup's 90,112**. Full walk-through in `CLINE-NINFER.md`.

xhigh finally has room: the Qwen card's official reasoning budget is 262,144, and our
measured natural stops run 15K to beyond 48K — impossible inside a 104K window, trivial
inside 252,928. The ASK-XHIGH lane uses output 131,072 with a **121,856-token prompt budget
(still bigger than the entire old window)**. Daily Cline stays at medium/32,768.

### Cline settings on ninfer — both profiles

| | daily driver (medium) | full capability (xhigh) |
|---|---|---|
| Base URL | `http://127.0.0.1:8080/v1` (or the Tailscale IP) | same |
| Model ID | `qwen3.8-27b` | same |
| Context window | 252,928 | 252,928 |
| Max output | 32,768 | **131,072** |
| Reasoning effort | medium | xhigh |
| Usable prompt | ~220K (2.4x the vLLM setup) | ~122K (still > the entire old window) |
| Temperature | unset / 1.0 | unset / 1.0 — a client-forced 0 overrides the official thinking sampling (1.0 / top-p 0.95) and invites repetition loops on 100K-token thinks |

### Remote access (optional)

The server binds `0.0.0.0` inside WSL, which WSL2's NAT keeps off your LAN by default. To
reach it from another machine, install Tailscale **inside WSL**
(`curl -fsSL https://tailscale.com/install.sh | sh`, then `tailscale up --hostname=qwen-5090`)
and use that node's tailnet IP — `serve-wsl.sh` keeps the daemon alive automatically. Bearer
auth is always on. Nothing is exposed to the LAN or the internet.

### First live Cline session on ninfer (xhigh) — measured minutes in

14 requests / ~523K prompt tokens into the first real session:

- **Turn starts: 150–272 ms at ~50K context.** ninfer's completion log names the path
  (`reuse=append_frontier`): each Cline turn extends the resident sequence — e.g.
  `prompt=50,515 cache=50,321`, 99.6% of the prompt served from cache, ~194 tokens actually
  prefilled. The same turn shape measured ~5s on the vLLM stack (the hybrid-SSM hit cost):
  **~20x faster turn starts, live, not simulated.**
- Reuse across the session: 12 of 14 requests, **454,593 tokens** served from cache.
- Decode: **137.7 tok/s session average** under xhigh at ~50K context (battery numbers at
  small context: 155–210 tok/s by mode). MTP acceptance on the latest request: 99/138 (72%),
  per-position 37/33/29.
- Per-request `usage.prompt_tokens_details.cached_tokens` (fix-branch commit 3) now reports
  the same numbers on the wire, so any client can watch its own hit rate.

### Residency-N: two conversations resident at once (validated, adopted)

The one real regression vs vLLM — "a FAST side-ask evicts your Cline session's cache" — is
fixed in fix-branch commit 4. Tracing ~5K lines of the engine showed retention already exists
per concurrency lane with best-reuse selection and page eviction; residency looked like 1 only
because tie-breaking sent every fresh request to lane 0, destroying its resident. The fix makes
selection retention-aware (most reuse -> unretained lanes -> LRU resident) and page reclaim
LRU-first. **Resident conversations now = `--max-concurrency`.**

Live validation on the patched binary (full battery, then production restored):

| | before | after |
|---|---|---|
| Interleaved A/B late-turn TTFT | 9.0 s (full re-prefill every switch) | **3.18 s** |
| Interleaved vs sequential @ 50K turn | ~2x sequential (full re-prefill) | **3.42 s vs 3.45 s — identical** |
| Parity battery | — | toolab 20/20, streamtool 3/3, multiturn 2/2, cache-hit 12/12 "NO REGRESSION" |

JSONL forensics confirm both conversations reusing their full prior context from turn 2
onward, alternating request-by-request. Design, alternatives considered (vLLM-style per-block
state snapshots rejected — hybrid-GDN physics), and the validation plan live in
`RESIDENCY-DESIGN.md`.

What keeps vLLM installed: **logprobs** (verifier / best-of-N tooling requires them; ninfer
returns none), video-capable fallback, and ecosystem maturity. After cutover it boots
on-demand for those jobs exactly the way ninfer used to boot for FAST.

Reproduce any of it: `toolab.py`, `needleprobe.py`, `clinesim.py` (sequential + interleaved
TTFT), `conc2big.py` (admission), `endure.py` (`CTX_SIZES` env), `cachehit-eval.py`,
`vidprobe.py` + `genvid2.py` (large-font clip), `vision-probe.py`, `phase2.sh` /
`phase2b.sh` / `phase2c.sh` / `phase2d.sh` (the exact batteries), `nfix_patch.py` +
`nfix2_patch.py` (the parser fixes as applied). All honor `TARGET_URL`/`QWEN_URL`/`EVAL_URL`.

## Part II — Setting up ninfer from scratch (humans and AI agents)

Everything in this section was executed and verified on this machine — commands are literal,
expected outputs are stated, and each step has a gate. Follow it top to bottom and there is
nothing left to guess. Paths assume this repo lives at `C:\Users\StevenPC\Downloads\qwen38`
(WSL view: `/mnt/c/Users/StevenPC/Downloads/qwen38`) and ninfer lives in `/opt/ninfer` inside
WSL — adjust both consistently if yours differ.

### Requirements (verified)

- RTX 5090 — ninfer targets `sm_120a` exclusively; no other GPU works
- WSL2 Ubuntu (we run Ubuntu-26.04) with an NVIDIA driver supporting CUDA 13.1
- CUDA Toolkit 13.1+ inside WSL (we build with 13.2 at `/usr/local/cuda-13.2`)
- CMake 3.28+, Ninja, a C++20 host compiler, git, python3
- ~25 GB free under `/opt` — the model artifact alone is 21.5 GB

### Step by step

**1. Clone and pin.** The four patches below are validated against upstream commit `feaf4dd`;
newer master usually works, but the patchers are assert-guarded — on anchor drift they refuse
loudly instead of mis-patching.

    sudo mkdir -p /opt/ninfer && cd /opt/ninfer
    git clone https://github.com/Neroued/ninfer.git src
    cd src && git checkout feaf4dd

**2. Apply the validated fixes** (needed until [#66](https://github.com/Neroued/ninfer/issues/66)
lands upstream — without them, string-declared tool arguments containing JSON break Cline's
`write_file`, `True` booleans arrive as strings, and no reuse telemetry reaches the API):

    W=/mnt/c/Users/StevenPC/Downloads/qwen38
    python3 $W/nfix_patch.py     # schema-typed arguments (code)
    python3 $W/nfix_test.py      # its unit tests + docs note
    python3 $W/nfix2_patch.py    # vLLM-parity scalar coercion  -> NFIX2_PATCH_OK
    python3 $W/nfix3_patch.py    # cached_tokens usage telemetry -> NFIX3_PATCH_OK
    python3 $W/nfix4_patch.py    # residency-N lane selection    -> NFIX4_PATCH_OK

Each exits 0 and prints progress; rerunning prints "already patched" and changes nothing.
An `AssertionError` means upstream drifted — stop and reconcile, never hand-edit around it.

**3. Configure, build, unit-test** (the exact configuration this repo's numbers came from):

    cmake -S /opt/ninfer/src -B /opt/ninfer/src/build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
      -DCMAKE_CUDA_COMPILER=/usr/local/cuda-13.2/bin/nvcc
    cmake --build /opt/ninfer/src/build --parallel
    /opt/ninfer/src/build/tests/ninfer_tool_call_parser_test   # must print: ok
    /opt/ninfer/src/build/tests/ninfer_openai_schema_test      # must print: ok

**4. Model artifact + integrity.** 21.5 GB download; any `hf` CLI works (ours lives in the
vLLM venv). The SHA-256 is non-negotiable — on mismatch, delete and re-download.

    /opt/qwen38/venv/bin/hf download neroued/Qwen3.8-27B-nvfp4-NInfer \
      qwen3_8_27b_nvfp4.ninfer --local-dir /opt/ninfer/models
    sha256sum /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer
    # bb3360522a06e136e0367f5703414d26272b7285c8a6ab6194135c17dbd81b32

**5. API key.** One line in `api-key.txt` in the Windows folder (your own secret). It is
`.gitignore`d — never commit it, never echo it into logs.

**6. Pick a profile** in `ninfer-prod.conf` — these are measured optima, not suggestions:

    CTX=252928  VISION=0   # Option B (default): max text. 9s boot, ~1.0 GB free, 57s @ 173K prefill
    CTX=152576  VISION=1   # Option A: image+video input. 10s boot, ~2.2 GB free, 41s @ 135K prefill
    # never VISION=1 with CTX>152576: 192,512 boots but leaves ~0.5 GB free -> 11x slower prefill

**7. Boot + verification ladder.** `START-NINFER.bat` (server + NMON monitor; READY in ~10 s).
The kit boots with `--host 0.0.0.0` (API-key gated) so Tailscale/LAN clients work — stock
ninfer defaults to loopback-only. Then, in order:

    W=/mnt/c/Users/StevenPC/Downloads/qwen38
    curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $(cat $W/api-key.txt)" \
      http://127.0.0.1:8080/v1/models                      # 200
    bash $W/ctokprobe.sh && tail -6 $W/logs/ctokprobe.log  # 2nd request: cached_tokens > 0
    cd $W && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions \
      /opt/qwen38/venv/bin/python toolab.py 2>&1 | tail -2 # total=20/20
    # optional deep check (~5 min):
    cd $W && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions NEEDLE_SIZES=96000,173000,236000 \
      /opt/qwen38/venv/bin/python needleprobe.py           # found=3/3 at every size

**8. Point Cline at it** — settings below. **9. Rollback** any time: `STOP-NINFER.bat`
(stops ninfer, boots the vLLM stack, waits for health 200).

**Updating an existing install.** If you cloned this repo as your working folder, `git pull`
refreshes docs, kit scripts, harnesses, and patchers — but never the engine itself. When a
pull brings a new `nfixN_patch.py`, apply it and rebuild: run `python3 $W/nfixN_patch.py`,
rerun step 3's `cmake --build` + unit gates, and the next START-NINFER boots the new binary
(the running server keeps the old one until then). Patchers are idempotent and assert-guarded,
so rerunning the full set after a pull is always safe. The model artifact, `api-key.txt`, and
`/opt/ninfer` are deliberately not in git — they never update via pull.

### Cline settings (validated optima)

OpenAI Compatible · Base URL `http://127.0.0.1:8080/v1` (Tailscale: `http://100.119.25.65:8080/v1`)
· API key from `api-key.txt` · Model ID `qwen3.8-27b`

| | medium — daily driver | xhigh — full capability | vision day (conf Option A) |
|---|---|---|---|
| Context window | 252,928 | 252,928 | **152,576** |
| Max output | 32,768 | **131,072** | 32,768 (49,152 if you want xhigh+vision) |
| Reasoning effort | medium | xhigh | medium |
| Usable prompt | ~220K | ~122K | ~120K |
| Temperature | unset / 1.0 | unset / 1.0 — **never 0**: it overrides the official thinking sampling (1.0 / top-p 0.95) and invites repetition loops on 100K-token thinks | unset / 1.0 |

Keep one effort per task (changing it busts prefix reuse — the instruction lives at the prompt
head). Expect xhigh turns to think for minutes; that is the trade. Measured on the first live
xhigh session: 150–272 ms turn starts at ~50K context, ~138 tok/s decode.

### Troubleshooting (every entry actually happened here)

- **NMON says READY but Cline can't connect** -> binding. Stock ninfer listens on `127.0.0.1`
  only; the kit passes `--host 0.0.0.0`. Tailscale runs *inside* WSL here, so loopback-only
  means invisible to remote clients.
- **`--vision` + 252,928 refuses to boot** -> doesn't fit 32 GB. That's physics, use a profile.
- **Second big concurrent request gets HTTP 503** -> fail-fast admission when the KV pool can't
  hold both. By design; retry when the first drains. 90K + 30K coexist fine at 252,928.
- **Custom wrapper script dies instantly at boot** -> if its filename contains `ninfer-serve`
  and it cleans up with `pkill -f ninfer-serve`, it kills itself. Use `pkill -x ninfer-serve`
  (the kit already does).
- **A FAST side-ask makes the next Cline turn slow once** -> you're on a pre-commit-4
  binary (residency 1). With all four patches applied, Cline and side-asks each keep their own
  resident (residency = `--max-concurrency`); rerun `nfix4_patch.py`, rebuild, restart.

### Hand this to an AI agent (copy-paste runbook)

    You are setting up the ninfer inference server for Qwen3.8-27B NVFP4 on an RTX 5090
    machine running WSL2 Ubuntu. Work strictly step by step. After every step, run its
    verification gate; if a gate fails, STOP and report the exact output — do not improvise
    around failures. Never print the API key. Do not change any server flag, sampling value,
    or config number beyond what is written here: these are measured optima.
    Paths: Windows folder C:\Users\StevenPC\Downloads\qwen38 = WSL
    /mnt/c/Users/StevenPC/Downloads/qwen38 (call it $W). Server tree: /opt/ninfer.

    1. PREFLIGHT. Verify and report: nvidia-smi shows RTX 5090; a CUDA toolkit >= 13.1
       exists under /usr/local/cuda-13*; cmake >= 3.28; ninja; python3; >= 25 GB free
       under /opt. Any miss -> STOP.
    2. CLONE. git clone https://github.com/Neroued/ninfer.git /opt/ninfer/src, then
       cd /opt/ninfer/src && git checkout feaf4dd.
    3. PATCH. Run in order: python3 $W/nfix_patch.py ; python3 $W/nfix_test.py ;
       python3 $W/nfix2_patch.py ; python3 $W/nfix3_patch.py ;
       python3 $W/nfix4_patch.py. Gate: every one exits 0
       (progress lines, or "already patched"). An AssertionError -> STOP (upstream drift).
    4. BUILD. cmake -S /opt/ninfer/src -B /opt/ninfer/src/build -G Ninja
       -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
       -DCMAKE_CUDA_COMPILER=/usr/local/cuda-13.2/bin/nvcc (use your cuda-13.x path),
       then cmake --build /opt/ninfer/src/build --parallel. Gate: build completes; then
       /opt/ninfer/src/build/tests/ninfer_tool_call_parser_test and
       .../ninfer_openai_schema_test each print exactly "ok".
    5. MODEL. hf download neroued/Qwen3.8-27B-nvfp4-NInfer qwen3_8_27b_nvfp4.ninfer
       --local-dir /opt/ninfer/models (any hf CLI; 21.5 GB). Gate: sha256sum of the file
       equals bb3360522a06e136e0367f5703414d26272b7285c8a6ab6194135c17dbd81b32. On
       mismatch: delete the file and STOP.
    6. KEY. Ensure $W/api-key.txt exists: exactly one line, no trailing whitespace.
       Do not display its contents.
    7. PROFILE. Ensure $W/ninfer-prod.conf contains CTX=252928 and VISION=0 (text
       default), or CTX=152576 VISION=1 for vision. Never VISION=1 with CTX above 152576.
    8. BOOT. Interactive: the user double-clicks START-NINFER.bat. Headless:
       nohup bash $W/ninfer-serve-prod.sh >/dev/null 2>&1 &. Gate: within 60 s,
       curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(cat $W/api-key.txt)"
       http://127.0.0.1:8080/v1/models returns 200. If a remote client will connect,
       also verify the same on the machine's Tailscale/LAN IP.
    9. TELEMETRY GATE. bash $W/ctokprobe.sh; in $W/logs/ctokprobe.log the first usage
       shows "cached_tokens": 0 and the second shows cached_tokens > 0.
    10. TOOL GATE. cd $W && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions
        /opt/qwen38/venv/bin/python toolab.py (any python3 with stdlib works). Gate:
        total=20/20.
    11. OPTIONAL DEEP GATE (~5 min). Same env, NEEDLE_SIZES=96000,173000,236000,
        run needleprobe.py. Gate: found=3/3 at every size.
    12. REPORT. Output a table: step, gate, result. State the profile booted, the
        VRAM used (nvidia-smi), and that rollback is STOP-NINFER.bat. Done.

## Part III — The bake-off and the fix branch

How ninfer earned production: the head-to-head evaluation, the wire-protocol bug it exposed,
the four commits that fixed everything, and the cache-architecture findings behind Residency-N.

### The ninfer bake-off (same model, same card, a from-scratch C++ engine)

[ninfer](https://github.com/Neroued/ninfer) is a 5090-exclusive C++/CUDA engine whose
Qwen3.8-27B NVFP4 artifact is built from the same unsloth checkpoint this repo serves. We
benchmarked it head-to-head with the identical eval suite. Measured here, WSL2, desktop loaded:

| | ninfer (int8 KV, its published config) | This repo's vLLM stack |
|---|---|---|
| Boot to serving | **~10s** | ~2.5 min |
| Short codegen | **186 tok/s** | 115.6 |
| Long reasoning | **155 tok/s** | 65–89 |
| Structured output | **210 tok/s** | ~115 |
| 18K repeat turn | 0.28s | 2.4–3.6s |
| Code accuracy (unit-tested) | **16/16** | 16/16–24/24 |
| Long-context needles | **3/3 at 96K, 173K and 236K prompt tokens** | validated to ~90K window |
| Image probe | 2/2 | 2/2 |
| Tool calls, 20-call A/B | **20/20 after our upstreamed fix** (12/20 stock — see below) | **20/20** |

The 236K needle run (perfect retrieval, int8 KV) verifies the long-context claim on this
card. The early "video can't read text" result was our probe's fault, not the model's — see
the large-font retest below, where ninfer reads every code and beats vLLM doing it.

**The schema bug — found, root-caused, fixed, and upstreamed.** In 20 tool calls across
five content shapes, stock ninfer failed exactly the two JSON-file shapes (0/8) and passed
everything else. Root cause in `src/serve/tool_call_parser.cpp`: every `<parameter=...>`
value is typed by *sniffing* (`parsed.is_discarded() ? raw : parsed`) — the request's
declared tool schema is never consulted, so a `type: string` parameter whose text happens to
parse as JSON goes out as an object. Cline writing a `.json` file through `write_file` hits
this on every attempt. We patched it on a fork branch (`fix/schema-typed-tool-arguments`):

- **Commit 1** — type parsed values by the declared parameter schema (string-declared values
  are never promoted; undeclared parameters keep value inference). 20-call matrix: 12/20 → **20/20**.
- **Commit 2** — the extended battery then caught scalar spellings: `True` for a
  boolean-declared parameter isn't valid JSON, so it survived as the string `"True"` (vLLM
  emits `true` there via constrained decoding). We ported vLLM's qwen3coder coercion table:
  any-case `null` → JSON null, string family verbatim, `int*`/`uint*` strict integral parse
  with raw fallback, `number`/`float` with integral collapse, boolean any-case `true`/`1`,
  union types (`["string","null"]`) → first non-null member. Their unit suite passes with 3
  new tests; a 6-shot live boolean probe returns properly typed
  `{"drain_first": true, "target_replicas": 7}` every time.

- **Commit 3** — reuse telemetry: Chat Completions usage now carries
  `prompt_tokens_details.cached_tokens`, fed by the same counter as the `cache=` log line and
  mirroring ninfer's own Responses-API `input_tokens_details` field. Live-validated: an
  identical repeat request reports `cached_tokens: 78` of 82 prompt tokens.

- **Commit 4** — residency: retention-aware lane selection + LRU retained eviction. Root cause
  of "one resident conversation only" was admission tie-breaking (zero-reuse requests always
  landed on lane 0, trampling its resident), not memory. +40/-10 policy-only change; see
  `RESIDENCY-DESIGN.md` for the full trace and field survey.

Upstream: filed as [Neroued/ninfer#66](https://github.com/Neroued/ninfer/issues/66) with the
repro table and fix design (issue-first per their CONTRIBUTING); PR offered from the branch.
The residency commit stays in our fork by choice for now — it changes scheduling behavior, and
we'd rather run it ourselves first than presume upstream wants it.

#### The full parity battery (Phase 2 — run at both windows)

Same eval suite as the vLLM production stack, patched ninfer, int8 KV, MTP-3, concurrency 2:

| Probe | ninfer @ 106,496 | ninfer @ 252,928 | vLLM production (104K) |
|---|---|---|---|
| Coding eval (unit-tested) | **24/24** | **24/24** | 24/24 |
| Tool-call probes | 3/3 | 3/3 | 3/3 |
| Long-context probes | 2/2 | 2/2 | 2/2 |
| Streaming tool calls (Cline mode) | 3/3, zero leaked content | — | 3/3 |
| Multi-turn tool replay | 2/2 | — | 2/2 |
| Needles | — | **3/3 at 96K / 173K / 236K** | 3/3 inside its 90K window |
| Concurrency 2 (two streams) | **288.6 tok/s aggregate** | — | n/a (SEQS=1) |
| 22-min varied-load endurance | **150 req, 0 errors, wall ratio 0.99, drift 87 MiB** | 47 req, 0 errors, ratio 1.11, drift 172 MiB | flat only after our KV_BYTES pin (stock collapsed 27x) |
| MTP acceptance (whole run) | 64.0% (68,021/106,334) | — | content-dependent 34–96% |
| Effort dial (none/low/medium/xhigh) | 0.1s / 21.1s / 40.5s / 16K-cap length | — | same science |
| Boot to serving | 9–10 s | 9 s | ~2.5 min |

Two operational behaviours worth knowing: requests that cannot fit the KV pool alongside a
running giant get an immediate **HTTP 503** (fail-fast admission — retry when the first
drains; at realistic sizes, 90K + 30K coexist fine), and the pool is fixed at boot — no
request-time growth, which is *why* endurance is flat with zero tuning.

#### Cache architecture: continuation vs radix — measured, not assumed

ninfer logs per-request reuse (`cache=` in the completion log; since fix-branch commit 3
the same number also reaches the wire as `usage.prompt_tokens_details.cached_tokens`). The checkpoint battery's per-request sequence
settles the semantics: identical repeat of a recent prompt → near-total reuse (~15.3K of
15.3K tokens); a *different* question over the same 15.2K document → **zero** reuse. It is a
**continuation/replay cache** (new prompt must extend or re-play a recent resident sequence),
not vLLM's serve-any-shared-prefix radix tree. At evaluation time the resident set was
effectively **1**; fix-branch commit 4 later made it **= `--max-concurrency`** (see the
Residency-N section below).

A Cline-shaped TTFT test (8 turns, ~12.5K tokens each) on both stacks, **measured before
commit 4**:

| | growing conversation, late-turn TTFT (87–100K prompts) | two conversations alternating (50K each) |
|---|---|---|
| ninfer | **4.1s** (server logs confirm ~351K tokens reused) | 9.0s — full re-prefill on every switch (residency 1) |
| vLLM | 5.1s (metrics: 144,000 of 250,988 queried tokens hit) | 9.8s — blows past the 115,587-token pool, eviction pressure |

Two findings we didn't expect. First, on this hybrid-SSM model a vLLM prefix **hit still
costs time linear in conversation length** (SSM state handling) — which is why long Cline
tasks start turns slower even at 80% hit rates. Second, both stacks degrade on interleaved
long conversations, just differently: ninfer predictably (one re-prefill, ~13s at 90K), vLLM
by eviction luck. That diagnosis held up almost exactly: it *was* purely a matching-policy
change, and fix-branch commit 4 implements it (retention-aware lane selection — the pool
already fit two conversations all along). Interleaved late-turn TTFT after the fix: **3.18s**,
with a 50K interleaved turn indistinguishable from sequential. Details in the Residency-N
section and `RESIDENCY-DESIGN.md`.

#### Vision & video head-to-head (and the config ceiling)

With a large-font test clip (the honest retest of the earlier artifact):

| | image (stack-trace screenshot) | video (6 planted codes) | vision boot cost |
|---|---|---|---|
| ninfer `--vision` | 2/2 + 2/2, **1.9–2.5s** | **12/12 digits across 2 runs, 2.5–4.2s** | boot still ~10s, +2.7 GB fixed |
| vLLM `VISION=1` | 2/2 + 2/2, 2.8–6.3s | 11/12 (one digit misread), 21.7–29.2s | **boot 252s**, KV pool unchanged |

The vision context ceiling on a 32 GB card is real and sharp (all measured, three configs):

| ninfer config | boots? | free VRAM after startup | 135–173K prefill | verdict |
|---|---|---|---|---|
| `--vision` + 252,928 | **no** (doesn't fit) | — | — | impossible |
| `--vision` + 192,512 | yes | ~0.4–0.5 GB | **620–681s (11x slow)**, image probe flaky | trap — do not use |
| `--vision` + 152,576 | yes | ~2.2 GB | **41.2s**, needles 3/3, image 2/2 | the vision profile |
| text-only + 252,928 | yes | ~1.0 GB | 57s @ 173K | the default profile |

The `--media-cache-mib` / `--media-live-mib` knobs bound *payloads*, not the fixed vision
reservation (tested; they return no VRAM). Net: **vision costs ~100K of context** on this
card. Both profiles live in `ninfer-prod.conf` (Option B text-max default, Option A vision).
On the vLLM fallback side, `--limit-mm-per-prompt`, `--mm-processor-kwargs max_pixels`, and
`--mm-processor-cache-gb` are the equivalent diet levers if its 252s vision boot matters to you.

## Part IV — The vLLM stack (validated fallback)

The original stack, fully documented and one click from live (`STOP-NINFER.bat` restores it).
The VRAM rule and the reasoning-effort findings below apply to both stacks.

### Measured performance

Reference machine: Ryzen 9 5900X / 32GB RAM / RTX 5090 32GB / Win11 + WSL2 Ubuntu-26.04.
All numbers from the validation run on 2026-08-18, production config, bare desktop.

| Scenario | Result |
|---|---|
| Short coding reply, thinking off | **115.6 tok/s** |
| Sustained thinking, 3,000 tokens out | 33.2-33.7s per response |
| 30K-context reasoning | **142.7 tok/s**, first token 7.14s cold / **2.44s cached** |
| 4 overlapping requests (queued, see note) | 107.9 tok/s aggregate |
| 60K-context first token | **7.1-7.8s** (was 210.8s before the MNBT fix — see below) |
| Sustained long code generation with thinking | **89-99 tok/s** |
| Decode rate across all reasoning-effort levels | 65-116 tok/s (tracks MTP acceptance — see below) |
| VRAM stability | flat: 29,520 MiB across a 14-minute varied-load run |
| **Code accuracy** | **24/24** unit-tested problems |
| **Tool-call validity** | **3/3** |
| **Long-context bug-finding** | **2/2** |
| **Accuracy on prefix-cache-HIT paths** | **18/18**, identical to cold (see vLLM #47861 below) |

The previous-gen Qwen3.6-27B on the same card (NVIDIA NVFP4 via Docker, Marlin kernel path)
peaked at 72-77 tok/s. This is ~1.5-1.6x faster on a newer model with 96K context.

Kernel check that matters: the boot log must show `FlashInferCutlassNvFp4LinearKernel` — the
native Blackwell FP4 tensor-core path. If it shows Marlin instead, you are on a weight-only
fallback and leaving ~40% of the speed on the table.

### Requirements

- RTX 5090 (or another 32GB Blackwell card), recent NVIDIA driver (610+)
- Windows 11 with WSL2, ~60GB free disk, 32GB system RAM
- No Docker. No Hugging Face account (the model is public).

### Setup (two double-clicks)

1. **`SETUP.bat`** — installs Ubuntu-26.04 under WSL2, sizes `.wslconfig`, installs the pinned
   Python/CUDA stack, fetches the official chat template, downloads the model (~22GB).
   15-40 minutes depending on your connection. Safe to re-run.
2. **`START-QWEN.bat`** — boots the server. ~5 minutes the first time (compiles and autotunes
   kernels, cached afterward), ~2.5 minutes on later boots. Ready when the log shows
   `Application startup complete`.

Then point any OpenAI-compatible client at:

- **Base URL:** `http://127.0.0.1:8000/v1`
- **Model:** `qwen3.8-27b`
- **API key:** auto-generated on first run into `api-key.txt` (unique per machine; delete to rotate)

Stop with `STOP-QWEN.bat`. Closing the server window also stops it. It does **not** auto-start
on boot, by design.

### Client settings (Cline / Roo / Continue / any OpenAI client)

| Setting | Value | Why |
|---|---|---|
| Context Window Size | **96000** | Keeps the peak prompt under the 90,112 hard ceiling with margin: even a worst-case 90% condense trigger peaks near ~86,400, and the recommended 60% auto-condense leaves far more. See "the cap is prompt + output" |
| Max Output Tokens | **16384** | Thinking shares this budget — starving it truncates turns mid-tool-call |
| Temperature | **1.0, explicitly set** | Some clients send 0 by default; greedy decoding makes thinking models loop |
| Reasoning Effort | **medium** | Default is `xhigh`. See the effort section below — this is the single biggest quality-of-life setting |
| Auto-condense threshold | **~60%** | Compaction requests are LLM calls too; they fail if the conversation is already huge |

Anything you don't send (top_p / top_k / min_p) falls back to the checkpoint's recommended
values (0.95 / 20 / 0). The server never overrides client-sent values; it only fills gaps.

### The cap is prompt + output, not prompt

This is the single most misread number in the whole setup. `--max-model-len` bounds
**prompt + generated tokens together**, so your usable prompt is `max-model-len` minus
whatever the client sends as `max_tokens`. vLLM says so itself when you cross it:

> "you requested 16384 output tokens and your prompt contains at least 90113 input tokens,
> for a total of at least 106497 tokens"

Measured on this build — perfectly linear, no slack:

| Prompt | max_tokens | Result |
|---|---|---|
| 89,371 | 16,384 | accepted (sum 105,755) |
| 90,113 | 16,384 | **rejected** |
| 103,555 | 2,048 | accepted |

So with the recommended 16,384 output budget:

| max-model-len | Usable prompt |
|---|---|
| 98,304 (old default) | 81,920 |
| **106,496 (current)** | **90,112** |

Which is why the window was raised. It costs +274 MiB of workspace and the KV pool actually
grows slightly (115,587 vs 113,624, block-size rounding); what shrinks is the pool's *surplus*
over the window, 15,320 → 9,091 tokens, which showed up as +0.29s on cached first-token while
cold prefill got 1.8s **faster**. Net, close to a wash for +8,192 usable prompt tokens.

Note this reverses an older rule from this project. Under percentage-based sizing, raising
`max-model-len` shrank the pool so hard that 88K wouldn't boot. Pinning the pool with
`--kv-cache-memory-bytes` removed that coupling entirely.

**Don't push to 110K.** The ceiling would reach 96,256, but Cline condenses well before
filling its configured window. (The exact trigger varies by Cline version and by your
auto-condense setting; a widely repeated ~81% figure could not be verified against Cline's
source, so this repo does not rely on it.) At 96,000 even a worst-case 90% trigger peaks
near ~86,400 — under the current
ceiling. You would pay real latency (surplus collapsing to ~2,950 tokens) for headroom the
client structurally never reaches.

#### About that "4 overlapping requests" row

The default profile runs `--max-num-seqs 1`, so those four requests **queue** — that number is
throughput while working through a backlog, not four parallel streams. It is kept as a
regression signal because Cline really does overlap requests (a normal turn arriving while an
auto-condense call is in flight), and it catches scheduler pathologies. It does **not** mean
this profile serves four users; use `START-SHARED.bat` for that.

### The locked configuration, and why every flag is there

```
vllm serve unsloth/Qwen3.8-27B-NVFP4
  --served-model-name qwen3.8-27b
  --host 0.0.0.0 --port 8000 --api-key <api-key.txt>
  --max-model-len 106496                # 104K. Usable PROMPT = this minus your max_output
  --kv-cache-dtype fp8_e4m3             # halves KV cost; quality-validated (see below)
  --gpu-memory-utilization 0.90         # ceiling only; the KV pool is pinned explicitly
  --kv-cache-memory-bytes 5000000000    # 5.0 GB, pinned. THE determinism knob (pool: 115,587 at the 104K default)
  --max-num-seqs 1                      # single-user profile; raise for shared use
  --max-num-batched-tokens 2048         # THE fix. Was 12288. See "the silent 27x slowdown"
  --language-model-only                 # drops the vision tower, frees ~1-3GB (coding use)
  --async-scheduling                    # overlaps CPU scheduling with GPU work
  --compilation-config '{"cudagraph_mode": "FULL_AND_PIECEWISE"}'
  --chat-template chat_template_official.jinja   # reasoning_effort lives in this template
  --reasoning-parser qwen3              # thinking separated into message.reasoning_content
  --enable-auto-tool-choice --tool-call-parser qwen3_coder
  --enable-prefix-caching --mamba-cache-mode align --prefix-match-unit 16
  --speculative-config '{"method": "mtp", "num_speculative_tokens": 3}'
```

Every value is an environment variable override, no editing required:
`CTX`, `KV_DTYPE`, `UTIL`, `KV_BYTES`, `SEQS`, `MNBT`, `SPEC_TOKENS`, `SPEC=0`, `NO_PREFIX=1`,
`KERNEL_FALLBACK=1`.

Env the script sets for you: `HF_HOME`, `CUDA_HOME` pointing at the venv's cu13,
`MAX_JOBS=4`, `NVCC_THREADS=2`, persistent FlashInfer-autotune and Triton cache dirs (this is
what makes warm boots 2.5 min instead of 5), and `VLLM_ENGINE_READY_TIMEOUT_S=1800`.

### Profiles

| Command | Context | Slots | Use |
|---|---|---|---|
| `START-QWEN.bat` (default) | 104K | 1 | Daily driver. Every benchmark above was measured on this |
| `START-SHARED.bat` | 60K | 4 | Two people / parallel agents. Lower context so 4 slots fit the pool |
| `START-VISION.bat` | 96K | 1 | Screenshots / mockups. Costs ~1.7s on cached first-token |
| `ASK-XHIGH.bat` | n/a | 1 | Deep-think one-off. Small prompt, ~90K output room, 4-10 min |
| `ASK-MEDIUM.bat` | n/a | 1 | Quick one-off ask at medium. Seconds. Try this first |
| `CTX=49152 bash serve-wsl.sh` | 48K | 1 | Heavy desktop use (wallpaper tools, a game idling) |

Whatever you change, leave `MNBT` at 2048 on a 32GB card and keep `KV_BYTES` pinned. Note that
raising `SEQS` without lowering `CTX` doesn't buy real concurrency: 4 slots x 96K would need
393K tokens of KV against a 113K pool, so requests just queue.

### The one rule that matters: keep desktop VRAM low

The server takes ~29-30GB of the card. If desktop apps (Wallpaper Engine, Chrome with hardware
acceleration, games) hold more than roughly 1.3GB, Windows starts **paging GPU memory** and
throughput collapses by 10x — while everything still "works", so it reads as a mystery slowdown.

`serve-wsl.sh` measures desktop VRAM before loading the model and prints a loud `PREFLIGHT`
warning if you are over budget. Check `logs/serve.log` for that line whenever performance feels
off. To find the culprit: Task Manager -> Details tab -> add the **Dedicated GPU memory**
column -> sort descending.

The script also writes `logs/gpu-watch.csv` every 60 seconds while serving. On a healthy config
that column is *flat*. If it climbs toward 32,000 MiB, something is oversubscribed — read the
next section.

### The silent 27x slowdown — root cause and fix

This is the finding that justifies the whole repo. Symptom: **the server is fast right after
boot and progressively collapses over the next 10-15 minutes of real work.** No error, no OOM,
no warning in any log. `/health` returns 200 the entire time.

#### What it looks like

Sustained varied-load run, cycling 1K / 8K / 20K / 40K / 60K contexts, on the old config
(`--max-num-batched-tokens 12288`):

| Elapsed | Context | tok/s | First token | VRAM |
|---|---|---|---|---|
| 0.1 min | 1K | 745 | 5.7s | 30,961 MiB |
| 2.1 min | 8K | **4.1** | — | 31,236 MiB |
| 3.7 min | 20K | **5.4** | — | 32,125 MiB |
| 10.0 min | 40K | 108 | **374.8s** | 32,086 MiB |
| 13.6 min | 60K | 93 | **210.8s** | 32,092 MiB |

VRAM pinned at 32,1xx MiB out of 32,607 — 98.5% of the card — and stayed there. Six minutes
to first token on a 40K prompt.

#### Why it happens (and why nothing errors)

Two mechanisms stacked:

1. **Peak activation memory scales with `--max-num-batched-tokens`, not with context length.**
   At 12288 the budget was structurally oversubscribed: 21.2GB weights + 4.5GB KV + 1.8GB CUDA
   graphs + ~4GB activations + 0.5GB desktop ≈ 32.1GB = the entire card. It fits at boot,
   because activations are only allocated when a large prefill actually runs.
2. **WSL2 ignores NVIDIA's "CUDA - Sysmem Fallback Policy".** On native Windows, exceeding VRAM
   raises an OOM you can see. Under WSL2 the driver silently spills to system RAM instead
   ([microsoft/WSL#11050](https://github.com/microsoft/WSL/issues/11050)). Everything keeps
   working, 10-50x slower, over the PCIe bus. **This is why there is no error to find.**

So: any tuning advice that relies on "raise utilization until it OOMs, then back off" is
actively wrong under WSL2. The OOM never fires. You have to measure.

#### The fix

`--max-num-batched-tokens 2048`. Same run, same load pattern:

| Elapsed | Context | First token | VRAM |
|---|---|---|---|
| 0.5 min | 40K | 7.76s | 29,629 MiB |
| 1.8 min | 60K | **7.29s** | 29,517 MiB |
| 2.4 min | 60K | 7.14s | 29,521 MiB |
| 3.4 min | 40K | 7.82s | 29,520 MiB |
| 4.3 min | 8K | 5.97s | 29,520 MiB |

**60K first token: 210.8s -> 7.29s.** VRAM flat within 600 MiB for the whole run, ~2.6GB of
headroom permanently free. No cost in context, accuracy, or precision — the 24/24 code score
was measured *on this config*.

The old value came from a real optimization (MNBT 12288 genuinely does raise cold-prefill
throughput on an idle server). It just wasn't survivable under sustained load on a 32GB card.
If you have more VRAM, raise it; on a 5090, don't.

### Pin the KV pool, don't let vLLM guess

vLLM sizes the KV pool from whatever VRAM is free at boot. Across boots on this machine that
produced pools of 85K, 96K, 104K, 109K, 128K and 158K tokens — the same command, different
results, silently eating the headroom that keeps the config stable.

`--kv-cache-memory-bytes` makes it deterministic. Swept at MNBT 2048, CTX 98304:

| KV bytes | Pool (tokens) | VRAM at boot | VRAM peak | Free floor | Cached TTFT |
|---|---|---|---|---|---|
| 4.4 GB | 99,580 | 27,873 | 29,375 | 3,232 MiB | 4.21s |
| **5.0 GB** | **113,624** | **28,514** | **30,006** | **2,601 MiB** | **4.18s** |
| 5.6 GB | 127,667 | 29,044 | 30,514 | 2,093 MiB | 6.10s |
| 6.2 GB | 141,710 | 29,610 | 30,862 | 1,745 MiB | 9.12s |

(The sweep also logged a cold-prefill TTFT column, but it read 0s on three of the four runs —
the harness misses TTFT when the first chunk arrives inside its sampling interval. It is
omitted here rather than reported; the decision rests on the free floor and the cached TTFT,
both of which were measured cleanly on every run.)

5.0 GB is the knee. Below it you buy nothing measurable; above it the free floor drops under
~2.1GB and cached latency degrades monotonically (4.18s -> 6.10s -> 9.12s) — the same paging mechanism, just arriving later. The 113,624-token
pool comfortably exceeds the 98,304 context window, and that surplus is what powers prefix
caching (4.18s cached vs 8.98s cold at 30K).

Boot is now reproducible — matched across independent boots to within ~80 MiB. Note the
sweep above ran at the earlier 96K window; the signature to check depends on the profile:

| Window | Boot log shows | vram_boot |
|---|---|---|
| **104K (shipped default)** | **`GPU KV cache size: 115,587`** | ~28,555 MiB |
| 96K (the sweep above, START-VISION base) | `GPU KV cache size: 113,624` | ~28,436 MiB |

Same 5.0 GB pin in both — the pool token count shifts slightly with the window because block
sizes round differently. If your boot line shows one of these two numbers, nothing has drifted.

---

### reasoning_effort: the dial nobody mentions

Qwen3.8 supports `reasoning_effort` with levels **xhigh (default), medium, low** — plus
thinking off entirely via `chat_template_kwargs: {"enable_thinking": false}`. The mechanism is
a single instruction injected by the official chat template; `medium` injects nothing at all,
so it is the model's natural depth.

Measured here, two prompts, 9,000-token output budget:

| Prompt | Effort | Wall time | Tokens out | Answer produced? |
|---|---|---|---|---|
| easy | low | 23.3s | 2,373 | yes |
| easy | medium | **9.4s** | 908 | yes |
| easy | xhigh | 12.5s | 985 | yes |
| hard | low | **73.1s** | 6,705 | yes |
| hard | medium | 81.7s | 7,564 | yes (most complete) |
| hard | xhigh | 119.8s | 9,000 | **no — burned the entire budget thinking** |

Two things this settles:

1. **Effort changes token *count*, not token *rate*.** Decode held at 75-102 tok/s at every
   level. "xhigh is slow" really means "xhigh writes 4x as much".
2. **The default (`xhigh`) is why the model appears to hang.** On the hard prompt it consumed
   a 9,000-token budget and emitted zero answer characters. Set `medium` in your client and
   most "it thinks forever" complaints disappear.

`low` is not reliably faster — on the easy prompt it produced *more* tokens than medium
(it skips planning and rambles). Use medium as the default; xhigh only for genuinely hard
one-off problems where you can afford a large output budget.

---

### Do NOT use reasoning_effort xhigh for agent coding

The template's default is `xhigh`, and that default is actively harmful for coding work. This
was measured, not assumed — the full unit-tested eval run at each level, same session, same
problems:

| | xhigh | medium |
|---|---|---|
| Code problems passed | **9/24** | **24/24** |
| Tool calls | 3/3 | 3/3 |
| Long-context | 2/2 | 2/2 |
| **Wall clock** | **1,533s** | **360s** |

4.3x slower for a third of the score. But the *reason* matters, because it is not what it looks
like. Every failure carried `finish_reason: "length"`:

| finish_reason | count | passed |
|---|---|---|
| `stop` (finished) | 9 | **9/9 — 100%** |
| `length` (hit the cap) | 15 | **0/15 — 0%** |

Perfect correlation. **xhigh never once produced a wrong answer — it produced unfinished
ones.** When it was allowed to finish it was correct every single time. The quality of its
reasoning is not the problem; it simply does not stop.

The obvious next question is whether a bigger budget rescues it. It does not. Re-running the
failures at **16,384 tokens** — a realistic Cline `Max Output` setting, nearly 3x the eval's
default — still gives **6/12**, with every failure again a truncation:

| Problem | xhigh @ 6K | xhigh @ 16,384 | medium @ 6K |
|---|---|---|---|
| version_compare | 2/3 | 2/2 | 3/3 |
| toposort | 1/3 | 2/2 | 3/3 |
| apply_patch | 0/3 | 1/2 | 3/3 |
| json_path | 0/3 | 1/2 | 3/3 |
| lru_ttl | 0/3 | **0/2** | 3/3 |
| wildcard_match | 0/3 | **0/2** | 3/3 |

When xhigh succeeded it used 2,429 / 6,144 / 6,565 / 11,727 / 12,294 / 12,932 tokens. When it
failed it consumed the entire 16,384 and ran **200-240 seconds** producing nothing usable.
Medium finished all of the same problems correctly, every time, under 6,000 tokens.

There is a matching signal in the speculative-decode counters: MTP acceptance falls to **34%**
at xhigh versus 58% at medium, dragging decode to 65 tok/s. Reasoning tokens are simply less
predictable to the draft head, so xhigh is slower per token *and* emits several times more of
them.

**Set `reasoning_effort: medium` explicitly in every client.** Leaving it unset gives you
xhigh, because that is the template default — this is the single most impactful client setting
on the whole stack. See the section above for why no output-budget setting rescues xhigh on
32GB, and what the one legitimate use for it is.

#### A note on the thinking_token_budget escape hatch

vLLM 0.27.1 does support `thinking_token_budget` (a top-level chat-completions field) which
caps thinking specifically. It works — a prompt that produced 0 answer characters at
`max_tokens: 2000` returned a complete 2,561-character answer with `thinking_token_budget: 300`.
But swept against medium as a control it never wins:

| Arm | Score | Wall |
|---|---|---|
| **medium** | **8/8** | **307s** |
| xhigh + budget 2,500 | 2/8 | 378s |
| xhigh + budget 4,000 | 4/8 | 694s |
| xhigh + budget 6,000 | 6/8 | 1,040s |
| xhigh + budget 8,000 | 6/8 (plateau) | 1,200s |

It also changes the failure mode for the worse: capped-thinking failures return
`finish_reason: stop` — confidently wrong answers rather than detectably truncated ones.

One caveat if you use it anyway: vLLM issue #44676 reports that on Qwen3.5+ the budget tracker
does not treat `<tool_call>` as an implicit reasoning end, so it can inject the reasoning-end
string into the middle of tool-call JSON and poison conversation history. Confirmed present in
this build (`thinking_budget_state.py` contains zero references to `tool_call`). It did not
reproduce in 8/8 clean tool calls here, but the issue reports ~0.5% incidence in production —
a small sample cannot rule it out.

Reproduce with `EVAL_EFFORT=xhigh python codeeval.py --tag xh --samples 3`.

### How much room does xhigh actually need? (and why no setting fixes it)

The natural follow-up to the section below: every xhigh failure was truncation, so does a
bigger output budget fix it? The honest answer required measuring where xhigh *naturally
stops* rather than repeatedly capping it. Given a 48,000-token ceiling and a realistic ~20.5K
coding prompt:

| Problem | Natural stop | Time | Result |
|---|---|---|---|
| lru_ttl | 15,493 | 237s | pass |
| lru_ttl (2nd sample) | 21,500 | 275s | pass |
| schedule | 25,686 | 341s | pass |
| wildcard_match | 41,356 | 571s | pass |
| cont_frac | **>48,000** | 612s | **truncated — nothing usable** |

Median 23,593. **Range 15.5K to beyond 48K for the same class of task — a 3x+ spread.**

Two conclusions, and they point opposite ways:

1. **xhigh's reasoning is fine.** 4 of 5 passed once it wasn't starved, and the one failure was
   again truncation, not a wrong answer. The earlier 9/24 was an artifact of a 6,000-token cap.
   Qwen's own model card explains why: it specifies **262,144 tokens for reasoning content**.
   Every practical budget on a 32GB card is a small fraction of the design point.
2. **No client setting makes it reliable here.** Because `max-model-len` bounds prompt +
   output together, buying output room costs context:

   | Max Output | Safe Cline context window | Cost vs 96,000 |
   |---|---|---|
   | 16,384 (default here) | 96,000 | — |
   | 32,768 | 90,000 | 6,000 |
   | 48,000 | 70,000 | 26,000 |
   | 64,000 | 50,000 | 46,000 |

   (The window values assume Cline condenses before its configured window fills; the exact
   trigger is version-dependent — see the caveat in "The cap is prompt + output".)

   Even 48,000 — a quarter of your context window — was not enough for `cont_frac`. And medium
   solved that same problem in **3,405 tokens and 36 seconds**, a 14x token multiplier in
   medium's favour, with medium being the one that got it right.

**Verdict: medium for all agent and coding work.** The cost of xhigh is not merely slowness;
it is unbounded and unpredictable slowness, on a budget you cannot make large enough without
gutting your context.

#### `QWEN-ASK.bat` — one launcher, with the numbers attached

Double-click it and pick a mode. Each option shows what it actually costs, measured here, so
the choice is informed rather than a guess:

| Option | Effort | Budget | When |
|---|---|---|---|
| **1 QUICK** | medium | 16,384 | **Recommended.** 24/24 and 8/8 in every test. 20-60s |
| 2 DEEP THINK | xhigh | 90,000 | One hard problem, small prompt, 4-10 min |
| 3 FAST | low | 8,192 | Snappier — but `low` is not reliably faster end-to-end |
| 4 NO THINKING | off | 8,192 | Fastest first token (~0.15s), simple lookups |
| 5 CUSTOM | your choice | your choice | With reference points printed for each |
| 6 | — | — | Prints the measured accuracy/speed/acceptance data |

Option 6 exists so the trade-offs live where the decision is made rather than only in this
file. Measured on one identical question, the effort ladder is visible in the output length
alone: thinking off 38 tokens, low 142, medium 173.

#### Every output budget we tried, and what happened

The full record, so nobody has to re-derive it:

| `max_tokens` | `thinking_token_budget` | Result | Note |
|---|---|---|---|
| 2,000 | none | **0 answer chars** | burned the whole budget thinking |
| 2,000 | 300 | complete answer, 1,225 tok | the budget mechanism does work |
| 6,000 | none | **9/24** | the original alarming number — all 15 failures were truncation |
| 8,000 | 2,500 | 6/8 | on the four problems that had failed |
| 16,384 | none | **6/12** | Cline's real setting; still truncating |
| 16,384 | 2,500 | 2/8 | worse — capped thinking gives confidently wrong answers |
| 16,384 | 4,000 | 4/8 | |
| 16,384 | 6,000 | 6/8 | |
| 16,384 | 8,000 | 6/8 | plateau — more budget stopped helping |
| **48,000** | none | **4/5** | one problem still exceeded it after 612s |
| 60,000 | none | works | smoke test, small prompt |
| **90,000** | none | works | `ASK-XHIGH.bat` default |
| *(medium, for contrast)* | | **24/24 and 8/8** | at 6,000 |

And where xhigh naturally stops when nothing caps it, with a realistic 20.5K prompt:
**15,493 · 21,500 · 25,686 · 41,356 · >48,000**. Median 23,593.

The shape of that data is the whole argument: there is no single number you can put in a
client setting that is both large enough for the tail and small enough to leave you any
context. Only a small prompt escapes the trade.

#### The one place xhigh does work: `ASK-XHIGH.bat`

Rather than degrading your Cline config to accommodate it, use xhigh where it actually fits —
a *small* prompt, which leaves nearly the whole 106,496-token window free for reasoning:

**Double-click it** — it prompts for an optional file to attach and then your question, so
you never need a terminal. From a command line it also takes arguments directly:

```
ASK-XHIGH.bat "why does this deadlock when two workers retry at once?"
ASK-XHIGH.bat --file src\worker.py "find the race condition"
```

`ASK-MEDIUM.bat` is the same tool at medium effort with a 16,384 budget — seconds instead of
minutes, and the effort level that won every test here. Reach for that one first; use
ASK-XHIGH when you have genuinely tried medium and want a second, slower opinion.

With a ~100-token prompt there is room for ~90,000 output tokens — roughly double the largest
natural stopping point we measured, so it finishes. It streams, shows the thinking gap, and
reports real token counts from the API rather than counting stream deltas (which undercounts,
and this build does not reliably split `reasoning_content` in streaming mode).

Measured on the smoke test: 3,012 output tokens in 43s at 69 tok/s — the expected xhigh decode
rate, with essentially all of it thinking and a short final answer.

This keeps Cline on medium at full 96,000 context while still giving you a genuine deep-think
mode for the hard one-off question. That is the answer to "can I have xhigh as an option":
yes, just not inside the agent loop.

### MTP speculative decoding: what acceptance actually looks like

`num_speculative_tokens: 3` means the MTP head proposes 3 tokens per step and the main model
verifies them. Accepted tokens are free throughput; rejected ones are wasted compute. Measured
per workload from vLLM's own counters (`vllm:spec_decode_*`):

| Workload | Acceptance | Mean accepted per draft | Decode |
|---|---|---|---|
| Short codegen, thinking off | **96.3%** | 2.89 of 3 | fastest |
| Long code generation, effort medium | 58.5% | 1.75 of 3 | 88.9 tok/s |
| Cached repeat of that same task | 58.0% | 1.74 of 3 | 89.2 tok/s |
| Deep reasoning, effort xhigh | **34.0%** | 1.02 of 3 | 65.4 tok/s |
| **Lifetime across a mixed session** | **67.8%** | **2.03 of 3** | — |

Per draft position, lifetime: position 0 accepted **82.3%**, position 1 **66.8%**,
position 2 **54.2%**.

Two things fall out of this:

1. **This is the hard evidence for depth 3 over depth 2.** The third draft position still lands
   more than half the time across a real workload mix. Dropping to 2 forfeits that outright,
   which is exactly what the earlier head-to-head measured (depth 3 was 27% faster).
2. **Acceptance is the mechanism behind the effort/speed relationship.** Deep reasoning isn't
   slower merely because it emits more tokens — it emits *less predictable* tokens, so
   acceptance collapses from 96% to 34% and per-token speed falls with it. Structured code is
   highly predictable to the draft head; open-ended reasoning is not.

Note that prefix caching does not change acceptance (58.0% cached vs 58.5% uncached) — the two
optimizations are independent. Reproduce with `specstats.py`.

### Vision: what it actually costs (measured, 3 boots)

Qwen3.8-27B is a VL model. The default config passes `--language-model-only`, which drops the
vision tower. Whether that's the right call changed once we pinned the KV pool by bytes, so it
was re-measured rather than assumed.

**The vision tower is bf16 — unsloth did not quantize it to NVFP4.** 333 tensors, 0.92GB on
disk, ~1.14GB resident. You pay full price for it.

| | Default (vision off) | Vision @ KV 5.0GB | Vision @ KV 4.4GB |
|---|---|---|---|
| KV pool | 113,624 tok | **113,624 tok** | 99,580 tok |
| Context | 96K | 96K | 96K (pool still > window) |
| VRAM at boot | 28,436 MiB | 29,575 MiB | 28,815 MiB |
| Free floor under load | 2,601 MiB | **2,040 MiB** | **2,615 MiB** |
| Short decode | 114.5 tok/s | 108.6 | 112.8 |
| 30K first token, cold | 8.98s | 11.07s | 11.03s |
| **30K first token, cached** | **3.58s** | **5.24s** | **5.26s** |
| 4-way concurrent | 105.0 | 101.1 | 100.6 |
| Reads a screenshot correctly | n/a | n/a | **2/2** |

Three things worth pulling out of that table:

1. **Context does not shrink.** With `--kv-cache-memory-bytes` pinned, the pool is fixed and
   the vision tower comes out of headroom instead. Older advice (including an earlier version
   of this README) said vision costs context — that was true only under percentage-based
   sizing.
2. **KV 4.4GB fully recovers the memory headroom** (2,615 MiB, matching the vision-off
   baseline) while keeping 96K context, because 99,580 still exceeds the 98,304 window.
3. **But cached first-token does not recover.** 5.24s at KV 5.0 and 5.26s at KV 4.4 against a
   3.58s baseline — nearly identical across two very different memory profiles. So that ~46%
   regression is **not** memory pressure; it is the cost of having the multimodal path active
   at all. You cannot tune it away by resizing the pool.

Image tokens are not free either. At patch size 16 with 2x2 spatial merge, an image costs
roughly `(w/16 x h/16) / 4` tokens: ~305 for a small 760x420 crop, but **~3,600 for a
full 2560x1440 screenshot**. Crop before pasting.

**Recommendation: keep it as a profile, not a default.** `START-VISION.bat` launches the
KV 4.4GB variant for when you need to paste a mockup or an error screenshot; `START-QWEN.bat`
stays lean for coding. Verify vision end-to-end with `vision-probe.py`, which renders a
synthetic stack-trace screenshot and checks that two planted values come back exactly.

### Is prefix caching safe here? (vLLM #47861)

vLLM [PR #47861](https://github.com/vllm-project/vllm/pull/47861), *"Fix MTP prefix cache
correctness for hybrid Mamba models"*, is an **unmerged draft**, and 0.27.1 is still the
newest release — so whatever it describes is live in every current build. It reports that MTP
speculative decoding combined with prefix caching on hybrid Mamba/GDN models misaligns
cache-hit lengths between the attention group and the mamba group, producing *"tool-call
leakage, recall failures and degenerate generations on cache-hit paths"*.

That is exactly this configuration. And a normal eval will not catch it, because a normal eval
sends fresh prompts — it never takes the cache-hit path.

`cachehit-eval.py` in this repo tests it directly. It runs an identical probe set twice
against an identical 13K-token codebase prefix: once with a unique leading salt (which
guarantees a cache **miss**, since vLLM matches from the first token) and once shared
(guaranteed **hit**), scraping `/metrics` to prove which path each pass actually took.

| | COLD pass | HOT pass |
|---|---|---|
| Prefix cache hit rate | **0.0%** | **86.3%** |
| Needle retrieval from the prefix | 9/9 | 9/9 |
| Code generation, unit-tested | 6/6 | 6/6 |
| Tool calls (valid + correct args) | 3/3 | 3/3 |
| Max repetition score | 0.046 | 0.063 |
| **Total** | **18/18** | **18/18** |

**No regression on the cache-hit path.** The reported corruption does not manifest on
Qwen3.8-27B at this configuration. Prefix caching stays on.

Two notes for anyone re-running this. The needle probes returned in 0.7-1.0s hot versus
2.6-2.8s cold, which is independent behavioural confirmation that the cache was live —
useful because vLLM 0.27.1 does not populate `prompt_tokens_details.cached_tokens` on this
path, so per-request `cached_tokens` reads `None` even on a hit. And give the code probes a
real output budget: at 3,000 tokens they cap out mid-function and score as failures that are
the harness's fault, not the model's. 7,000 is enough.

Re-run it with: `/opt/qwen38/venv/bin/python cachehit-eval.py --samples 3 --effort medium`
To A/B against no caching at all: `NO_PREFIX=1 bash serve-wsl.sh`.

### Accuracy validation

`codeeval.py` is an objective harness, not a vibe check: 8 non-trivial problems (interval
merging, version comparison, topological sort, token-bucket rate limiter, unified-diff patch
application, LRU+TTL cache, JSON path query, wildcard matcher), each scored by **executing a
real test suite** against the model's output. The suites were validated against reference
implementations first, so a failure can only be the model's.

On the production config: **24/24 code problems, 3/3 tool-call JSON validity, 2/2 long-context
planted-bug retrieval.** Re-run after raising the window to 104K: **24/24, 3/3, 2/2 again**, and
the cache-hit probe re-scored **12/12 cold and 12/12 hot** at an 82.5% hit rate. Independently
reproduced by a second reviewer pass (8/8, 1/1, 2/2 at one sample). `reasoning_effort: low`
also passes clean — **16/16, 2/2, 2/2** at two samples — making LOW a validated fallback,
though medium remains the recommended default (LOW is not reliably faster on easy prompts). Accuracy is not
the constraint on this setup — memory and scheduling are.

Run it yourself: `/opt/qwen38/venv/bin/python codeeval.py --tag mytest --samples 3`

### Battle log — setup problems, already solved

Each of these presents as something else entirely. If you deviate from the pinned stack, this
is your debugging map.

1. **Triton: "Failed to find C compiler"** — Ubuntu-26.04 ships without gcc.
   -> `apt install build-essential`.
2. **MTP draft head: "Could not find nvcc"** — CUDA *runtime* wheels don't include the
   compiler. -> `uv pip install nvidia-cuda-nvcc`.
3. **"CUDA compiler and CUDA toolkit headers are incompatible"** — nvcc 13.3 against torch's
   CUDA 13.2 headers. -> Pin nvcc to torch's exact version: `nvidia-cuda-nvcc==13.2.*`
   (check with `python -c "import torch; print(torch.version.cuda)"`). SETUP.bat does this.
4. **`ptxas fatal: Unsupported .version 9.3`** while FlashInfer builds CUTLASS FP4 kernels.
   -> Don't compile locally; install the prebuilt cache:
   `flashinfer-jit-cache==<flashinfer version> --extra-index-url https://flashinfer.ai/whl/cu130/`
   (1.4GB).
5. **Engine dies silently during warmup, no error** — WSL2 defaults to ~50% of host RAM and
   the parallel kernel compile gets OOM-killed. -> Raise the WSL memory cap for first-time
   setup, then **lower it to 16GB** once caches are warm. A 26GB cap starves Windows and
   freezes the desktop on cold boots. Also cap `MAX_JOBS=4`.
   Note: `autoMemoryReclaim` belongs under `[experimental]` in `.wslconfig`, not `[wsl2]` —
   it is silently ignored in the wrong section.
6. **Prefill stuck ~500 tok/s** — MTP caps the scheduler's batched tokens, and piecewise-only
   CUDA graphs leave throughput on the table. -> `--compilation-config
   '{"cudagraph_mode": "FULL_AND_PIECEWISE"}'`. (The companion fix used to be raising
   `--max-num-batched-tokens`; see the slowdown section for why that backfired.)
7. **Every turn re-reads the whole conversation** — vLLM silently sets
   `enable_prefix_caching=False` on hybrid-Mamba models like this one. ->
   `--enable-prefix-caching --mamba-cache-mode align --prefix-match-unit 16`
   (vLLM PR #46384). Repeat turns at 30K context: 8.98s -> 3.58s to first token.
   This mode is experimental; the optional nightly restart exists to bound its growth.
8. **`--default-chat-template-kwargs` wedges the whole server** — on vLLM 0.27.1 it accepts
   requests that then generate nothing, forever, with zero errors logged. -> **Never use it.**
   Configure effort per-client instead.
9. **ECONNREFUSED from Windows while WSL says healthy** — usually the server is mid-restart.
   Verify with `curl.exe http://127.0.0.1:8000/health` from PowerShell.
10. **Per-config flags are invisible to `--help`** — `vllm serve --help` does not list them.
    Use `vllm serve --help=CacheConfig`, `--help=MambaConfig`, etc. This repo's script
    auto-detects flag availability that way before passing anything.

#### Two real bugs fixed in `killall-vllm.sh` (worth stealing)

1. `pkill -f vllm` **matched the script's own filename** — the stop script killed itself
   before it could wait for VRAM to release. Every "restart" silently skipped its safety
   wait, allowing overlapping boots and CUDA OOM on the next start.
2. vLLM renames the engine subprocess to **`VLLM::EngineCore`** (uppercase). Lowercase
   patterns never matched it, so engine processes survived "restarts" still holding VRAM.
   After fixing this, the very next stop reported `killed=3`.

Both fixed with precise process patterns, case-insensitive matching, self-PID exclusion, and
a wait loop that blocks until `nvidia-smi` reports under 3,000 MiB used.

### Things that sound like optimizations but aren't (all tested here)

- **Raising `--gpu-memory-utilization` to 0.93-0.95 for "15% more VRAM".** This advice assumes
  an OOM will tell you when you've gone too far. Under WSL2 it never fires — you just get
  silent sysmem paging. Pin the KV pool explicitly instead and leave the utilization ceiling
  at 0.90.
- **4-bit KV cache to reach "121K / 212K context" on a 5090.** It does boot with a
  135,952-token pool. It also runs at **36 tok/s instead of 115**, and dropped
  `merge_intervals` from 3/3 to **0/3**. Every viral long-context claim for this card that we
  could trace back resolved to this trade. Not worth it.
- **`--mamba-ssm-cache-dtype bfloat16`.** Gives a real +10.5% KV pool (126,914 vs 114,900
  tokens) and is **broken on this build**: crashes the FlashInfer FP4 autotuner at boot, and
  with autotune disabled every generation returns HTTP 500 `CUDA driver error: device not
  ready`. Also note `auto` is **not** bfloat16 for this model — it resolves to the
  checkpoint's declared fp32 state, so advice claiming "auto already mirrors bf16" is wrong here.
- **`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.** Frees no measurable memory and
  **crashes the engine** (`CUDA driver error: device not ready`), both in the FP4 autotuner at
  startup and on 40K-context requests. Mechanism: PyTorch's VMM allocator can't safely remap
  blocks while vLLM replays static CUDA graphs, which `FULL_AND_PIECEWISE` guarantees it will.
  Gated behind `ALLOC_EXPAND=1` here and must stay off. Also check it isn't exported in your
  shell — child processes inherit it (`unset PYTORCH_CUDA_ALLOC_CONF`).
- **`VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0`.** Redundant once the KV pool is pinned by
  bytes; it only affects the profiler's estimate, which no longer decides anything.
- **"Align `--max-num-batched-tokens` to a multiple of the 1600 block" / "remove
  `--prefix-match-unit`".** Tested three-armed (2048 baseline vs 3200 aligned vs 3199 with the
  unit flag removed): hit rates 82.5-86.3% vs 80.8% vs **76.4%**, accuracy 12/12 on all,
  acceptance identical, and the non-default arms cost +816 and +948 MiB of boot VRAM. The
  scheduler source already aligns chunk boundaries to the block
  (`aligned_end = end // block_size * block_size`), so there was no misalignment to fix — and
  removing the match unit coarsens hit granularity exactly as vLLM's own flag docs predict.
- **Speculative depth 2** (a popular recommendation): measurably worse. Depth 3 was 27% faster
  than depth 2 on single-stream work and 64% faster than depth 1 — and the acceptance counters
  say why: draft position 2 still lands 54.2% of the time. Keep 3.
- **Disabling prefix caching** to avoid its experimental memory growth: costs 8.98s vs 3.58s
  on every repeat turn at 30K and saves nothing once MNBT is correct.
- **Swapping in the [froggeric "fixed" chat template](https://huggingface.co/froggeric/Qwen-Fixed-Chat-Templates)
  (v22.1, Aug 2026).** This one is worth taking seriously — it explicitly covers Qwen3.8-27B
  and explicitly targets vLLM — so it was tested properly by rendering both templates through
  jinja2 with vLLM's exact message shape. Result:

  | Condition | Outcome |
  |---|---|
  | `reasoning_effort: medium`, no tools | **byte-identical output**, 365 chars each |
  | No effort specified | Official injects the xhigh instruction (602 vs 365 chars) |
  | With tools | Fixed adds ~480 chars of tool-call discipline rules |
  | Prefix-cache stability over an 8-step agent loop | **1.000 vs 1.000** — tied, perfect on both |
  | Rendered size, 8-step tool-calling loop | Official 1,995 tok vs fixed 2,068 tok |

  Its headline claim — *"mutated past turns destroy the prefix cache"* — **does not reproduce
  on this model.** Measured as the longest common token prefix between consecutive renders,
  both templates keep 100% of the prefix stable at every step. Neither blanks prior reasoning,
  and neither emits empty `<think></think>` blocks in vLLM's message shape.

  What it genuinely fixes: the `xhigh` default (real — see the effort table above; but we
  already send `medium` explicitly, which makes the templates identical), and tool-argument
  crashes when `arguments` arrives as a JSON string. That second one **does not apply to
  vLLM**, which pre-parses arguments into a dict before the template sees them
  (`chat_utils.py`, "per the Transformers docs & maintainers"). It's a llama.cpp problem.

  The one thing it adds that we can't dismiss: extra prompt-level tool-calling guardrails
  ("no conversational text before the tool call", "tags at the start of a line, no
  indentation", "never nest `<tool_call>` blocks"). Both templates emit the same wire format
  (`<function=...>` inside `<tool_call>`), so **no parser change is needed** despite its
  README suggesting `qwen3_xml` — `qwen3_coder` handles both. We stay on official because
  tool-call validity here is already 3/3 cold and 3/3 on cache-hit paths, so there is no
  measured defect for those guardrails to fix, and they cost ~120 tokens on every
  tool-enabled request. If you ever see malformed tool calls in Cline, this is the targeted fix.

  A derivative template ("Qwen-Sharp": froggeric plus an 11-line terseness system prompt) was
  also A/B-tested by injecting its exact text as a system message: accuracy 7/8 vs 8/8
  control, code outputs came out *longer* (avg 2,073 vs 1,549 tokens) and 67% slower, and it
  did not tame xhigh thinking (its one xhigh completion vs the control's zero is inside the
  measured coin-flip variance). Styling the answer does not shorten the reasoning.
- **bf16 KV cache "for long-context quality".** fp8 scored 8/8 needle retrieval at both 40K
  and 88K. The reported degradation does not manifest here, and bf16 would halve your context.

## Credits

Built and measured over five days against a real Cline workload. Model by Qwen, NVFP4 quant by
Unsloth, serving by vLLM.
