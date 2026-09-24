# halow-fullmac-liveness-artifact

Artifact for *When Recovery Breaks Sessions: Liveness Failures across Firmware, Host, and Android in Wi-Fi HaLow FullMAC Stacks* (submission to Computer Communications).

Control-plane liveness models + board experiment harness + raw logs for the TXW8301 USB FullMAC on an A133 Android 10 platform.

## Layout

```
models/    Three executable models (pure Python 3, stdlib only, no deps)
  control_plane_model.py   single-port host stack, stock vs LHR, liveness check
  multi_sta_model.py       multi-STA session consistency, recovery amplification
  cross_layer_model.py     cross-layer ready deadlock + 16-way patch ablation
board/     Board experiment harness (adb shell scripts + Windows helpers)
  run_suite.sh / run_e4_watchdog.sh / run_multista_reconcile.sh / ...
  EXPERIMENT_RUNBOOK.md    step-by-step reproduction on hardware
  windows/                 Windows-side .bat/.ps1 wrappers
data/      Raw board logs (see data/README.md)
analysis/  Log parsers that produce the paper numbers
docs/      System model, experiment plan, related-work notes, firmware openness
```

## Quick start (models, no hardware needed)

```
python3 models/control_plane_model.py
python3 models/multi_sta_model.py
python3 models/cross_layer_model.py
```

Each prints the state-space size, liveness violations, minimal counterexample traces, and (cross_layer) the 16-subset patch ablation table.

## Reproduce the paper numbers

| Paper item | Data | Command |
|---|---|---|
| Table: board results (E4 17/17, EMS 20/20) | `data/20260922_205545_clean/`, `data/20260922_193407/` | `python3 analysis/summarize_board_results.py data/` |
| Table: heal time min/p50/max | same | `python3 analysis/analyze_time_to_heal.py data/` |
| Table: LHR overhead (1.57%) | `data/overhead_20260923_101922/` | `python3 analysis/summarize_board_results.py data/` |
| Fig. 2 / trap traces (3-step) | model output | `python3 models/cross_layer_model.py` |
| Wipe-then-rebuild trace table | `data/20260922_193407/` (EMS stock runs) | `python3 analysis/analyze_time_to_heal.py data/` |

Fisher exact tests quoted in the paper: EMS 9/20 vs 20/20 -> p = 6.1e-4; E4 17/17 -> p = 4.3e-10 (two-sided).

## Platform notes

- SoC: Allwinner A133, Android 10, kernel 4.9
- HaLow: TaiXin TXW8301 USB FullMAC (`hg0` netdev, `hgpriv` private commands, `/proc/hgicf/status`)
- **Firmware AP association limit = 8 STAs** (`SYS_STA_MAX` = 8 in the shipped build; the 31 option is commented out). Model sweeps go to N=24 to show scaling, but on this firmware the board-side reachable maximum is 8.
- LHR implementation details (3 s poll, 5 s RESP cap, `setprop vendor.a133.halow.rebind_net 1`) are described in the paper, Section "LHR implementation".

## Data notes

`data/salvage_e4/` is a partial-rescue dataset from an interrupted earlier session. **It is NOT cited in the paper** and is included for completeness only.

## License

MIT. See [LICENSE](LICENSE). Copyright (c) 2026 Shenzhen Root Innovation Technology Co., Ltd.
