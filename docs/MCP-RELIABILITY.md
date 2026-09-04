# MCP v1.3.0 reliability update

Released in this repository on 2026-09-04. This updates the text-only Claude delegation
bridge, preserving the existing five MCP tools and the xhigh / 131,072-output / 262,144-context
profile. It does not update NINFER, alter KV precision, or restart a deployed process.

## Fixed behavior

| Previous failure | v1.3.0 behavior |
|---|---|
| Clean EOF, partial SSE or a JSON error frame could become `done` | Validate JSON/SSE, require a finish reason and `[DONE]`, and surface failure |
| Output-limit truncation looked like a normal completed job | Return `incomplete`; retain partial answer text and show the reason |
| Tool failures always returned `isError: false` | Failed/incomplete operations use `isError: true` |
| Each MCP process maintained a separate in-memory registry and generation limit | Share atomic on-disk records, job ownership leases and one generation lock per local registry |
| A new process could treat another live process's jobs as lost | Check the job's ownership lock; recover only after that lease is gone |
| Cleanup sorted random UUID filenames | Retain the newest 50 terminal records by completion time and preserve queued/running records |
| The quick tool could block on HTTP for 90 seconds | Start a durable queued job, wait up to 45 seconds, then return its ID if still active |

The registry remains in `jobs/` beside the deployed script. Writes use a temporary file,
flush/fsync and atomic rename, protected by a registry lock. Per-job ownership and the
generation slot use POSIX `flock`; process termination releases held locks. A terminal
storage failure releases job ownership and logs the write failure, so readers do not keep
waiting indefinitely on a live but idle owner.

Existing completed v1.2 JSON records remain readable. Work interrupted by a process exit
is reported on the next lookup, with available partial snapshots; it is not resumed or
automatically retried. The bridge stores reasoning character counts, not reasoning text.

The generation lock is local to a shared jobs directory. It does not coordinate a Mac
with a PC, or direct Qwen Code/Cline requests with the bridge. The orchestration policy
still needs to avoid overlapping large xhigh jobs that cannot fit in the GPU's shared pool.

## Verification

From the repository root, on macOS or Linux/WSL:

```bash
python3 -B mcp/test_bridge.py
```

**20 tests passed on both macOS and WSL on September 4.** The suite loads no model, needs
no API key, and uses temporary job directories and a fake HTTP inference server. It covers:

- Valid reasoning/content/usage streams, multiline SSE and heartbeat comments.
- Empty/partial EOF, missing terminal signals, malformed JSON and server error frames.
- Output limits, unsupported tool output, partial-result error flags and argument errors.
- Chronological retention, preservation of active records and completed v1.2 records.
- Two actual MCP processes sharing status/results while serializing generations.
- Startup during another process's live job, owner termination and generation-lock release.
- Completed-result retrieval after all original MCP processes exit.
- Storage-failure lease release, unchanged default budgets and quick-call job handoff.

The optional live smoke check **does send short requests to NINFER**. Run it only when
the server has capacity, pointing at the deployed script beside its `api-key.txt`:

```bash
python3 mcp/mcptest.py /absolute/path/to/deployed/qwen_mcp.py
```

Set `QWEN_URL` for a remote endpoint. The smoke check uses explicit short none/low test
requests, handles the quick-call job-ID fallback, and fails if MCP reports an error or
incomplete job. These probe settings do not change the production xhigh policy.

## Activation and rollback

Follow [the upgrade steps](QWEN-MCP-SETUP.md#updating-an-existing-installation). Replacing
the script leaves current processes on their loaded code. Once jobs finish, fully quit and
reopen Claude; `qwen_health` must show **v1.3.0**. NINFER does not need a restart.

Keep the prior script as a backup. If a rollback is needed, finish active jobs, fully quit
Claude, restore that script, then reopen Claude. Avoid mixed live versions: v1.2 does not
use the new file locks or understand every new job status.
