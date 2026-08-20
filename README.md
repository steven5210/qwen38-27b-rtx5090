# Qwen3.8-27B on a single RTX 5090 — a validated, one-click local setup

Runs **Qwen3.8-27B (unsloth NVFP4)** on **vLLM 0.27.1** under WSL2, tuned and measured on a
desktop RTX 5090 (SM120, 32GB). OpenAI-compatible API with thinking, tool calling, **104K
context**, MTP speculative decoding, and prefix caching.

Every flag in here exists because something broke without it. The battle log is the real value
of this repo: a dozen problems that each cost hours, already solved — including one that makes
the server *silently* 27x slower after a few minutes of use, with no error anywhere.

## Quick reference

If you read nothing else, read this. Every value is measured, not guessed; the section links
explain why.

**Client settings (Cline / Roo / Continue)**

| Setting | Value | Why |
|---|---|---|
| Base URL | `http://127.0.0.1:8000/v1` | |
| Model | `qwen3.8-27b` | |
| API key | from `api-key.txt` | auto-generated on first run |
| **Context Window Size** | **96000** | [prompt+output cap](#the-cap-is-prompt--output-not-prompt) |
| **Max Output Tokens** | **16384** | thinking shares this budget |
| **Temperature** | **1.0, set explicitly** | some clients send 0; greedy decoding makes thinking models loop |
| **Reasoning Effort** | **medium** | [the single most impactful setting here](#do-not-use-reasoning_effort-xhigh-for-agent-coding) |
| Auto-condense | ~60% | compaction is an LLM call too |

**Server defaults** (all overridable by env var, no editing)

| | Value |
|---|---|
| Context | 104K (`CTX=106496`) → **90,112 usable prompt** at 16,384 output |
| KV pool | 115,587 tokens, pinned (`KV_BYTES=5000000000`) |
| Batched tokens | **`MNBT=2048`** — do not raise on a 32GB card |
| Slots / util | `SEQS=1`, `UTIL=0.90` |
| Spec decode | MTP depth 3 (67.8% lifetime acceptance) |
| Vision | off (`VISION=1` to enable, costs ~1.1GB) |

**Commands**

| | |
|---|---|
| `START-QWEN.bat` | daily driver |
| `STOP-QWEN.bat` | stop |
| **`QWEN-ASK.bat`** | **ask a question — menu of presets, or set effort/budget yourself** |
| `ASK-MEDIUM.bat` / `ASK-XHIGH.bat` | the same thing without the menu, for scripting |
| `START-VISION.bat` | screenshots / mockups |
| `MONITOR.bat` | live dashboard: boot progress -> READY, KV/cache/acceptance, VRAM paging alarms (auto-opens with START-QWEN) |
| `START-SHARED.bat` | two people, 60K context |

**The three things that will bite you**

1. **Desktop VRAM over ~1.3GB** → Windows pages GPU memory, 10x slowdown, no error. Close Wallpaper Engine.
2. **Reasoning effort left unset** → you get `xhigh`, the template default, which scored **9/24 vs medium's 24/24** here.
3. **Raising `--max-num-batched-tokens`** → looks like a prefill optimization, silently makes the server 27x slower after ten minutes.

---

## Measured performance

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

## Requirements

- RTX 5090 (or another 32GB Blackwell card), recent NVIDIA driver (610+)
- Windows 11 with WSL2, ~60GB free disk, 32GB system RAM
- No Docker. No Hugging Face account (the model is public).

## Setup (two double-clicks)

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

## Client settings (Cline / Roo / Continue / any OpenAI client)

| Setting | Value | Why |
|---|---|---|
| Context Window Size | **96000** | Keeps the peak prompt under the 90,112 hard ceiling with margin: even a worst-case 90% condense trigger peaks near ~86,400, and the recommended 60% auto-condense leaves far more. See "the cap is prompt + output" |
| Max Output Tokens | **16384** | Thinking shares this budget — starving it truncates turns mid-tool-call |
| Temperature | **1.0, explicitly set** | Some clients send 0 by default; greedy decoding makes thinking models loop |
| Reasoning Effort | **medium** | Default is `xhigh`. See the effort section below — this is the single biggest quality-of-life setting |
| Auto-condense threshold | **~60%** | Compaction requests are LLM calls too; they fail if the conversation is already huge |

Anything you don't send (top_p / top_k / min_p) falls back to the checkpoint's recommended
values (0.95 / 20 / 0). The server never overrides client-sent values; it only fills gaps.

## The cap is prompt + output, not prompt

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

### About that "4 overlapping requests" row

The default profile runs `--max-num-seqs 1`, so those four requests **queue** — that number is
throughput while working through a backlog, not four parallel streams. It is kept as a
regression signal because Cline really does overlap requests (a normal turn arriving while an
auto-condense call is in flight), and it catches scheduler pathologies. It does **not** mean
this profile serves four users; use `START-SHARED.bat` for that.

## The locked configuration, and why every flag is there

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

## Profiles

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

## The one rule that matters: keep desktop VRAM low

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

## The silent 27x slowdown — root cause and fix

This is the finding that justifies the whole repo. Symptom: **the server is fast right after
boot and progressively collapses over the next 10-15 minutes of real work.** No error, no OOM,
no warning in any log. `/health` returns 200 the entire time.

## What it looks like

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

## Why it happens (and why nothing errors)

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

## The fix

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

## Pin the KV pool, don't let vLLM guess

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

## reasoning_effort: the dial nobody mentions

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

## Do NOT use reasoning_effort xhigh for agent coding

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

### A note on the thinking_token_budget escape hatch

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

## How much room does xhigh actually need? (and why no setting fixes it)

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

### `QWEN-ASK.bat` — one launcher, with the numbers attached

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

### Every output budget we tried, and what happened

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

### The one place xhigh does work: `ASK-XHIGH.bat`

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

## MTP speculative decoding: what acceptance actually looks like

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

## Vision: what it actually costs (measured, 3 boots)

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

## Is prefix caching safe here? (vLLM #47861)

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

## Accuracy validation

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

## Battle log — setup problems, already solved

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

### Two real bugs fixed in `killall-vllm.sh` (worth stealing)

1. `pkill -f vllm` **matched the script's own filename** — the stop script killed itself
   before it could wait for VRAM to release. Every "restart" silently skipped its safety
   wait, allowing overlapping boots and CUDA OOM on the next start.
2. vLLM renames the engine subprocess to **`VLLM::EngineCore`** (uppercase). Lowercase
   patterns never matched it, so engine processes survived "restarts" still holding VRAM.
   After fixing this, the very next stop reported `killed=3`.

Both fixed with precise process patterns, case-insensitive matching, self-PID exclusion, and
a wait loop that blocks until `nvidia-smi` reports under 3,000 MiB used.

## Things that sound like optimizations but aren't (all tested here)

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

## Remote access (optional)

The server binds `0.0.0.0` inside WSL, which WSL2's NAT keeps off your LAN by default. To
reach it from another machine, install Tailscale **inside WSL**
(`curl -fsSL https://tailscale.com/install.sh | sh`, then `tailscale up --hostname=qwen-5090`)
and use that node's tailnet IP — `serve-wsl.sh` keeps the daemon alive automatically. Bearer
auth is always on. Nothing is exposed to the LAN or the internet.

## Credits

Built and measured over five days against a real Cline workload. Model by Qwen, NVFP4 quant by
Unsloth, serving by vLLM.
