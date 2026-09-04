# Delegating Claude work to local Qwen3.8-27B (MCP setup)

`qwen_mcp.py` gives Claude Desktop five tools for delegating text tasks to NINFER.
**Current bridge: v1.3.0 (2026-09-04).** It uses only Python's standard library on
macOS or Linux/WSL; native Windows Python is not supported because coordination uses
POSIX file locks. The original live workflow was validated on 2026-08-20; all 20
v1.3.0 regression tests passed on macOS and WSL with a fake inference server.

Claude can start more than one MCP process. Processes using the same local `jobs/`
directory share job status/results and serialize their generation requests. The bridge
returns text; **Qwen Code is a separate Mac client that executes tools in its worktree**.
Neither that client's jobs nor another machine's MCP registry are managed by this bridge.

## Install (one time, ~2 minutes)

1. Open `%APPDATA%\Claude\claude_desktop_config.json` (create it if missing).
2. Add the server (merge into an existing `mcpServers` block if you have one):

    {
      "mcpServers": {
        "qwen-local": {
          "command": "wsl.exe",
          "args": ["-d", "Ubuntu-26.04", "-u", "root", "--",
                   "python3", "-u", "/mnt/c/Users/StevenPC/Downloads/qwen38/qwen_mcp.py"]
        }
      }
    }

3. Fully quit Claude Desktop (system tray -> Quit) and reopen it.
4. Check: the tools icon in a new chat should list qwen_health / qwen_ask / qwen_submit /
   qwen_status / qwen_result. Say "run qwen_health" -- expect UP, **v1.3.0**, and the
   configured 262,144-token window. Older NINFER builds do not advertise their window;
   the health response labels the configured fallback explicitly.

Why wsl.exe: the server runs inside WSL where 127.0.0.1:8080 is guaranteed reachable
(same path every probe in this repo used). No Windows Python, no pip installs.

## Adding it on a MacBook (reaches the PC over Tailscale)

Requirements: Tailscale running on the Mac (same tailnet), the PC on with ninfer up,
and python3 present (macOS: `python3 --version`; accept the Xcode tools prompt if asked).

1. Make a folder, e.g. `~/qwen-mcp/`, containing:
   - `qwen_mcp.py` (`mcp/` in this repo — or let `mcp/mac-setup.sh` do steps 1-2 for you:
     it downloads the file, merges the Claude config with a backup, and checks the tailnet)
   - `api-key.txt` (same one line as on the PC)
2. Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

    {
      "mcpServers": {
        "qwen-local": {
          "command": "python3",
          "args": ["-u", "/Users/YOURNAME/qwen-mcp/qwen_mcp.py"],
          "env": {"QWEN_URL": "http://100.119.25.65:8080"}
        }
      }
    }

3. Fully quit Claude Desktop (Cmd+Q) and reopen. "run qwen_health" should say UP and v1.3.0.

The Mac reaches the same inference server over the tailnet. Its jobs live in
`~/qwen-mcp/jobs`; they are shared by MCP processes on that Mac, not with the PC's registry.
If Claude cannot resolve `python3`, use the absolute path returned by `command -v python3`
in the `command` field (for example `/opt/homebrew/bin/python3`).

## Updating an existing installation

Updating the bridge does **not** require a NINFER restart or a change to the Claude MCP
registration. Install the new script, then reload it on the next full Claude restart.

1. Pull this repository and optionally run `python3 -B mcp/test_bridge.py` from its root.
   The suite uses temporary records and fake HTTP responses, so NINFER may keep running.
2. Back up the deployed `qwen_mcp.py`. Keep `api-key.txt` and the `jobs/` directory.
3. Replace the script at the path already registered in Claude. To avoid a partially
   written script, copy to a temporary file in the destination directory, check its syntax,
   then rename it over `qwen_mcp.py`. Existing processes continue with their loaded code.
4. When current jobs finish, fully quit Claude (Cmd+Q on Mac; system tray -> Quit on
   Windows), then reopen it. Merely closing its window may leave MCP processes running.
5. Call `qwen_health` and confirm **v1.3.0**. A v1.2.0 response means an old process is
   still serving that session.

Completed v1.2 results remain readable. A job interrupted by a restart is reported as
failed/incomplete on lookup; it is **not automatically resumed or resubmitted**. Partial
answer snapshots may be available, but their presence does not mean the task finished.
Avoid mixing old and new live bridge processes: v1.2 does not participate in the new locks.

This update preserves **xhigh**, the **131,072-token output ceiling**, and the
**262,144-token context setting**. `QWEN_MCP_JOBS` is no longer used to raise concurrency;
v1.3.0 intentionally permits one generation per shared local registry.

## Daily workflow

1. START-NINFER.bat (or leave it running).
2. In Claude, just ask -- or better, add this standing instruction to your Claude
   preferences/project. It makes Claude JUDGE each task instead of pattern-matching a
   task list, with quality always ahead of token savings:

   > I have a local Qwen3.8-27B available through the qwen-local MCP tools, plus Sonnet and
   > Opus subagents where the session supports them. YOU (Fable) ARE THE ORCHESTRATOR; the
   > other models are your delegates. QUALITY ALWAYS BEATS TOKEN SAVINGS -- the goal is
   > eliminating unnecessary expensive-token spend, never accepting worse output.
   >
   > QWEN OPERATING PARAMETERS (fixed -- do not deviate): server window 262,144 tokens.
   > Every qwen_submit runs at reasoning_effort xhigh with max_tokens 131,072 (thinking and
   > answer share it) -- never lower the effort or output budget. That leaves a nominal
   > 131,072 tokens for the rendered prompt, including task, context, system and template
   > overhead. Leave margin: qwen_submit's character-based pre-check is approximate.
   > qwen_ask (effort none/low) is the only
   > sub-xhigh lane. Use qwen_status with wait:true instead of polling (chain sub-50s
   > waits for long jobs) and context_path for large file contexts.
   > If qwen_ask returns a job ID, follow that job instead of asking again. Only state
   > done is a completed result; incomplete/error and isError:true require inspection.
   > Run one large xhigh job at a time. Direct Qwen Code calls do not share the MCP lock.
   >
   > ROUTING -- for each subtask pick the CHEAPEST tier that delivers FULL quality (the
   > bar is identical at every tier; when in doubt between tiers, route UP):
   > 1. QWEN (free, xhigh-deep, 262K window, NO hands -- it returns text only): specified
   >    implementation, tests, and reviews against verifiable specs with cheap gates;
   >    bulk summarization. First choice whenever it qualifies. Benchmarked on a real
   >    merged PR: ~1M free local tokens replaced 2-3.5M expensive ones at equal
   >    post-review quality, zero takeovers.
   > 2. SONNET subagent (cheap, agentic hands, runs in parallel while the GPU is busy):
   >    mechanical application of payloads/diffs, file operations, running gates, and
   >    work beyond Qwen that is not judgment-heavy.
   > 3. OPUS subagent (bounded judgment): module-level design or debugging, deep review
   >    assists -- judgment work that still does not need you.
   > 4. FABLE (you): cross-cutting judgment, spec-writing, adjudication, final review --
   >    and any task where you are simply the best fit; route down only when a lower
   >    tier truly delivers full quality. Where subagents are unavailable (plain chats),
   >    the ladder collapses to Qwen <-> you.
   >
   > ESCALATION: a failure is diagnosed before it is escalated. Most delegate failures
   > are spec/context gaps -- fix the input and retry the SAME tier. A true capability
   > miss escalates to the tier the diagnosis indicates (skip tiers when the failure
   > class says so), carrying the spec plus the failure evidence. After two failed tiers
   > on one subtask, you take it over. Record every routing choice, escalation, and
   > whether results needed fixes -- calibration continues.
   >
   > NON-NEGOTIABLES at every tier: fully self-contained specs (delegates share none of
   > your context; failures usually trace to what you left out). Verify anchors, types,
   > and interfaces before applying returned code. Where a reference implementation or
   > ground truth exists, build a test probe against it IN THE PLAN, not the epilogue.
   > After ANY code change, whoever authored it, run the usual adversarial review and
   > /code-review flow. No tier self-certifies -- not Qwen, not Opus: you check the
   > output and own every verdict. If I ask you to delegate something you judge
   > unsuitable, push back with your reason and let me decide.

## The tools

| tool | what | latency |
|---|---|---|
| qwen_health | engine readiness, authenticated model lookup, window source, bridge version, shared local job states | short HTTP checks |
| qwen_ask | effort none/low, <=4K out; shares the queue; returns an answer or a job ID to follow | waits up to 45s |
| qwen_submit | background job, default **effort xhigh, max_tokens 131,072**; `context_path` reads a local file (<=2MB) so huge contexts never go through tool parameters | returns instantly |
| qwen_status | shared snapshot, or `wait:true` until done/error/incomplete (default 45s, capped at 50s); chain calls for long jobs; queued/running at the wait boundary is normal | snapshot / bounded wait |
| qwen_result | answer + usage (incl. cached_tokens); failed/incomplete jobs return an error with available partial answer text; thinking text omitted | snapshot |

## Reading results and handling interruptions

| Job state | Meaning | Next step |
|---|---|---|
| `queued` / `running` | Work is waiting or active | Continue `qwen_status` waits; do not resubmit |
| `done` | Stream ended with a valid stop reason and `[DONE]` | Fetch and validate the answer |
| `incomplete` | Output was truncated, interrupted after partial output, or contained unsupported tool output | Inspect error and partial answer; decide deliberately whether to resubmit |
| `error` | Request failed or the owning process exited before a recoverable answer | Inspect the error and underlying connection/service before retrying |

Failed/incomplete status and result calls carry MCP **`isError: true`**. An empty EOF,
malformed SSE frame or server error frame is never treated as success. An output limit
(`finish_reason: length`) is incomplete even when some answer text is present. The bridge
does not execute tool calls, retry work automatically, or certify generated code as correct.

## Limits and operation

- **Waits:** status waits are capped at 50 seconds to leave margin below the harness
  timeout seen in earlier versions. Quick asks use the same durable job mechanism and
  return the job ID after 45 seconds if necessary. A wait ending is not a job timeout.
- **Retention:** the newest 50 terminal results are kept by completion time, plus every
  queued/running record. Cleanup happens when a worker persists a terminal result.
  Results outside retention may report an expired/unknown ID.
- **Restart recovery:** ownership file locks distinguish a live job in another MCP
  process from an interrupted job. The OS releases a terminated owner's lock. Recovery
  occurs when job records are read; partial answer snapshots are saved periodically as
  output arrives. In-flight generation itself does not survive a process exit.
- **Concurrency:** all processes using the same local `jobs/` directory share one
  generation slot, including quick asks. Do not use a network share for the registry.
  NINFER still has two lanes, but two large xhigh requests may not fit together. Direct
  Qwen Code/Cline calls and MCPs on other machines are outside this local lock.
- **Payload:** the bridge caps the encoded JSON request at 2,000,000 bytes; the server's
  `--max-request-mib 2` allows 2,097,152 bytes. `context_path` avoids large tool arguments,
  but its contents still count toward the HTTP body and context limits.
- **Context:** preflight uses a character-based estimate, not exact tokenization. Keep
  margin for templates and tokenization differences. Health reports the server's window
  when available, otherwise it labels the 262,144 configured fallback. The submit budget
  remains configured at 262,144; a future server context change must be coordinated here.
- **Model profile:** xhigh and the 131,072 output ceiling remain the current delegation
  policy. The bridge still exposes effort/output fields for explicitly selected jobs;
  do not automatically reduce them to make a second large request fit.

See [MCP reliability implementation and tests](MCP-RELIABILITY.md) for the change list,
test command and the optional live smoke check. NINFER upgrades and VRAM/KV tuning are
separate work: production remains pinned pending workload validation, with no automatic
changes to inference capacity or reasoning budgets.
