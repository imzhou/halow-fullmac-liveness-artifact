# Clean extract from salvage_e4, suite results_20260922_205545

Source mix: `board_results/salvage_e4/` also contains older `193408` (INVALID: baseline watch=0).
This folder keeps **only** timestamps >= 20260922_205545.

## Suite header
```
suite out=.../results_20260922_205545 peers=172.16.0.100 172.16.0.101 npeers=2 N=20 RUN_E2=0
```
Stopped mid-suite (~round 17 EMS); E4 completed **17** paired stock/LHR rounds.

## E4 (primary, usable)

| Exp | Trials | self_heal=0 | self_heal=1 | baseline watch |
|-----|-------:|------------:|------------:|----------------|
| E4 stock | 17 | **17** | 0 | all watch=1 |
| E4 LHR | 17 | 0 | **17** | all watch=1 |

Fisher one-sided (stock fail > LHR fail): **p ≈ 4.3×10⁻¹⁰**

## EMS (partial this suite, prefer prior full 20)

Partial new-suite EMS also present under `ems/`; prefer `results_20260922_193408` (complete 20) for EMS claims.

## Verdict

**This is the E4 data we want.** No need to re-run E4 for statistics.
