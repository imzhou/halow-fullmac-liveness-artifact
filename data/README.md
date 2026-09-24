# Board log datasets

| Directory | Experiment | Cited in paper |
|---|---|---|
| `20260922_205545_clean/` | E4 watchdog: 17 paired runs (stock vs LHR), clean session | yes (Table: board results, heal times) |
| `20260922_193407/` | EMS multi-STA reconcile: 20 trials + 9 stock failures with wipe-then-rebuild signature | yes (Table: board results, trace table) |
| `overhead_20260923_101922/` | LHR polling overhead measurement (1.57% net) | yes (Table: overhead) |
| `salvage_e4/` | Partial rescue of an interrupted earlier E4 session | **NO - not cited, completeness only** |

Each run directory contains the raw adb-captured `.log` stream plus a per-run `result.json` / summary where produced by the harness.

Parsers: `../analysis/summarize_board_results.py` (aggregates run outcomes), `../analysis/analyze_time_to_heal.py` (heal-time quantiles + failure-signature counts).
