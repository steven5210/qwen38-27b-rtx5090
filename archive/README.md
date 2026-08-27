# archive/ — superseded, kept for the record

Everything here was real, ran on this machine, and produced numbers that still appear in the
main README. Each has since been replaced or retired — kept browsable instead of deleted so
the history sections keep their receipts.

| File(s) | What it was | Superseded by / retired because |
|---|---|---|
| `monitor.py` | Monitor generation 1 (vLLM-era, full-screen redraws) | `monitor/qmon.py` — flicker-free, follows both stacks, session stats |
| `nmon.py` | Monitor generation 2 (ninfer-aware, still redraw-based) | `monitor/qmon.py`; `NMON.bat` lives on as a QMON alias |
| `maintenance.ps1` + `REGISTER-MAINTENANCE.bat` | Daily 5am only-if-running vLLM restart, insurance against the experimental prefix cache's growth | Retired 2026-08-19: the MNBT fix + pinned KV pool made long-run degradation a non-issue, and ninfer boots in ~10 s anyway |
| `STOP-FAST.bat` | Stopped ninfer back when it was the experimental "FAST" side server next to production vLLM | `ninfer/STOP-NINFER.bat` (same kill, plus vLLM restore) |
| `phase2.sh` / `phase2b.sh` / `phase2c.sh` / `phase2d.sh` | The exact Phase-2 parity batteries from the bake-off (results tabulated in the README's Part III) | One-shot by design; the individual harnesses they drive live in `bench/` |
| `p2makeup.sh`, `p3cfg.sh` / `p3cfg2.sh` / `p3cfg3.sh` | One-off drivers from the vision-ceiling investigation (the 152K/172K/192K boundary hunt) | The verdicts are baked into `ninfer-prod.conf` and the README's ceiling tables |

Nothing here is wired into any launcher. If you resurrect one, mind that paths inside assume
the flat working-folder layout described in the main README.
