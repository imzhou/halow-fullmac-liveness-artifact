# Board suite summary, 20260922_193407

Primary: `raw/results_20260922_193408`  
Peers: `172.16.0.100 172.16.0.101` · **20 trials** · `RUN_E2=0`  
(Aborted partial: `results_20260922_180944`, 3 rounds only, not primary.)

## Counts

| Exp | Trials | self_heal=0 | self_heal=1 | Fisher vs LHR (one-sided) |
|-----|-------:|------------:|------------:|---------------------------|
| E4 stock | 20 | 1 | 19 | **INVALID** (see below) |
| E4 LHR | 20 | 0 | 20 | n/a |
| EMS stock | 20 | **9** | 11 | **p ≈ 0.0006** vs LHR 0/20 |
| EMS LHR | 20 | 0 | **20** | n/a |

## EMS (usable, Claim / C3 LHR)

- All 9 stock fails: `alive=0 sta_count=2` (stale two-STA table).
- LHR: always `alive=2 sta_count=2`.
- Combined with the prior 5-trial two-peer suite (2 fail / 3 heal): stock **11/25** fail vs LHR **0/25**, p ≈ **1.2e-4**.

## E4 (this run discarded)

- **All 20 rounds** baseline `watch=0` (oneshot watch not observed / not running).
- Stock "heals" in 3 to 7 s with watch still 0, so **another path** brings `hg0` UP (not the oneshot watch hypothesis).
- Keep prior clean E4 evidence: `results_20260918_202855` stock **0/5** heal; plus `20260922_165833` E4 stock **0/5** / LHR **5/5** (baseline had watch present in those older scripts).

## Action

- Paper: cite **EMS 9/20 vs 0/20** as primary board stats; E4 cite earlier 5+5.
- Re-run E4-only after fixing watch detection (`ps` cmdline) and **abort if baseline watch != 1**.
