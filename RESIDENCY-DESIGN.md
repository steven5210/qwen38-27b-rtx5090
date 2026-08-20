# Residency-N: findings, design, and validation plan

## What the engine actually does today (read at db3ded2, ~5K lines traced)

- Concurrency lanes each own a `SequenceState` that *survives request completion*
  (`retained=true`, KV pages held, token `ledger` + `ResidentPrefixIdentity` for compatibility,
  plus one optional server-side `rewrite_checkpoint` per sequence).
- Reuse per lane, two forms: **AppendAtFrontier** (new prompt extends the resident frontier —
  the live Cline path, 150–565 ms turn starts) and **rewrite-checkpoint restore** (prompt
  matches a retained mid-sequence checkpoint).
- Admission (`find_admission_lane`) already *plans against every free lane and prefers the one
  with the most reusable tokens*, and can evict other lanes' retained pages when the pool is
  tight. Retention machinery is complete and first-class.

## Root cause of the interleave miss — it is NOT missing capacity

Tie-breaking. Selection uses strict `reuse > selected_reuse`, so every zero-reuse request
resolves to the lowest free lane — lane 0 — and `FullReset` startup destroys that lane's
resident. Alternating conversations A/B therefore trample lane 0 forever while lane 1 never
accumulates a resident. Residency "1" was a scheduling artifact, not a memory limit: at
conc=2 the engine already retains two sequences with pages to match.

## Chosen design (phase 1): retention-aware lane selection — ~30 lines, policy-only

Selection key becomes lexicographic: (1) most reusable tokens; (2) among ties, prefer lanes
holding **no** retained sequence; (3) among retained ties, the **least-recently admitted**
resident (new per-lane admit stamps); (4) lane index. Same key for the eviction fallback, and
the page-reclaim loop evicts LRU-first instead of index-first. No new memory model, no new
state kinds, no protocol change; every downstream invariant (per-lane plans, versioning,
eviction accounting) is untouched.

Effect at conc=2: Cline and a FAST side-ask each keep a hot resident — the measured ~10–13 s
post-side-ask re-prefill disappears. In general **resident conversations = max_concurrency**:
raising `--max-concurrency` raises N, with pages still admission-gated exactly as today.

## Phase 2 (deferred): sequence slots decoupled from lanes (R > lanes). Real surgery across
SequenceState binding, stats, and eviction; unnecessary for the measured workload since the
concurrency knob already scales N.

## Why not radix / snapshot ladders (field survey)

This model is hybrid-GDN: linear-attention layers carry *recurrent state*, so serve-any-prefix
radix caching requires per-block state snapshots. That is vLLM's approach — granularity knobs,
"align"/"all" modes, Marconi-style admission — and their own tracker shows the cost: fragility
issues and hit latency linear in prefix length (we measured 5.9 s at 100K on a *hit*).
ninfer's frontier+checkpoint model is O(1) snapshots per sequence with 150–565 ms hits at
50–100K live. For K interleaved conversations, K resident frontiers is optimal in both memory
and latency; the only capability radix adds is mid-sequence divergence, which the existing
rewrite-checkpoint machinery partially covers and the Cline workload does not need.

## Validation plan (at the next natural server stop; nothing adopted before green)

1. Build in the isolated worktree (`/opt/ninfer/rn`, branch `feat/resident-prefixes`) — the
   production binary is never touched.
2. Existing unit suites must stay `ok` (policy change should alter no schema/parser behavior).
3. Live battery: clinesim INTERLEAVE at conc=2 — success = late-turn TTFT within ~2x of SEQ
   (today: 7.5 s vs 4.1 s means full re-prefill; target sub-1.5 s); then codeeval sample,
   streamtool, multiturn, conc2big, 10-min endurance — all at parity with the db3ded2 battery.
4. Upstream: propose with the measurement table (per CONTRIBUTING discuss-first), PR after.
