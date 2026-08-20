# Cline on ninfer — settings that are actually validated

Boot: double-click **START-NINFER.bat** (READY in ~10 s; NMON monitor opens alongside).
Server binds `0.0.0.0:8080` with API-key auth — reachable on loopback and the WSL Tailscale IP.
Back to vLLM: **STOP-NINFER.bat** (stops ninfer, boots the production vLLM stack, waits for health).

Cline -> API Provider: **OpenAI Compatible**
- Base URL: `http://127.0.0.1:8080/v1`  (remote via Tailscale: `http://100.119.25.65:8080/v1`)
- API key: contents of `api-key.txt`
- Model ID: `qwen3.8-27b`

| | medium (daily driver) | xhigh (full capability) |
|---|---|---|
| Context window | 252,928 | 252,928 |
| Max output | 32,768 | **131,072** |
| Reasoning effort | medium | xhigh |
| Usable prompt | ~220K | ~122K |
| Temperature | unset / 1.0 | unset / 1.0 (never 0 — overrides official thinking sampling, loops on long thinks) |

Vision day: flip `ninfer-prod.conf` to Option A (`CTX=152576`, `VISION=1`) and set the Cline
context window to 152,576. (192K+vision boots but is a validated trap: ~0.5 GB free starves
prefill 11x. Vision costs ~100K context on a 32 GB card.)

Measured on the first live xhigh session: turn starts 150–272 ms at ~50K context
(`reuse=append_frontier`, 99%+ of the prompt from cache), decode ~138 tok/s session average.
Known behaviours: a FAST side-ask evicts the resident conversation -> one full re-prefill on the
next turn (~10-13 s at 90K, then fast again); two 130K+ conversations at once -> the second gets
HTTP 503 until the first drains (fail-fast admission, just retry); keep one reasoning effort per
task (changing it busts prefix reuse on any stack).
