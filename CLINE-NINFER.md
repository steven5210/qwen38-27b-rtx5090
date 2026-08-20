# Pointing Cline at ninfer (Phase 3)

1. Double-click **START-NINFER.bat** (server READY in ~10 s; monitor window opens alongside).
2. In Cline settings -> API Provider: **OpenAI Compatible**
   - Base URL: `http://127.0.0.1:8080/v1`
   - API key: contents of `api-key.txt` (same key as vLLM)
   - Model ID: `qwen3.8-27b`
   - Context window: **252,928** (Option B default, text-only). If you flip `ninfer-prod.conf` to Option A (vision), use 152,576.
   - Max output tokens: **32,768** (usable prompt = window minus output)
3. Everything else (QWEN-ASK bats, ask scripts) already targets :8080 automatically when it is up.
4. To go back: **STOP-NINFER.bat** (kills ninfer, boots production vLLM, waits for health 200).

Notes
- Reasoning effort works as before (none/low/medium/xhigh); Cline's own setting passes through.
- After a FAST side-ask, the next Cline turn re-prefills the conversation once (~10-13 s at 90K+) -- known
  residency=1 behaviour, upstream feature request planned.
- Two giant (130K+) conversations at once: the second gets HTTP 503 until the first finishes -- by design
  (fail-fast admission), just retry.
