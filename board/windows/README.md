# Windows board experiments (pure .bat, no PowerShell)

## Who runs what

| Environment | Task |
|-------------|------|
| Local Windows | `adb` plus double-click / command-line `run_board.bat` |
| buildserver | Reads `board_results/`; runs no adb |

## Usage

From this directory on Z::

```bat
push_scripts.bat
restore_hg0.bat
run_board.bat snap

REM default suite: E4 stock + E4 LHR + EMS stock + EMS LHR (E2 off)
run_board.bat 5 172.16.0.100

REM Claim-2 multi-STA: pass >=2 camera IPs
run_board.bat 5 172.16.0.100 172.16.0.101
```

| Script | Effect |
|--------|--------|
| `push_scripts.bat` | Pushes the .sh files only |
| `restore_hg0.bat` | Soft recovery (up/IP/rebind) |
| `restore_halow_hard.bat` | Use when FWCTRL stops responding: USB rebind + rmmod/insmod + re-setup |
| `run_board.bat` | Push + run suite + pull (includes E4 LHR; E2 off by default) |

E2 (`hgpriv set sleep`) can wedge the firmware control channel and was removed from the default suite. To run it:

```bat
adb shell "RUN_E2=1 N_REPEAT=1 sh /data/local/tmp/halow_exp/run_suite.sh /data/local/tmp/halow_exp 172.16.0.100"
```

| `run_board.bat` argument | Meaning |
|--------------------------|---------|
| `snap` | Pull snap_status only |
| First number | Repeat count N (default 5) |
| Following IPs | Camera peers (Claim-2 needs >=2; default 172.16.0.100) |
| `-s SERIAL` | Pick an adb device |

Results: `board_results\<timestamp>\`

The output directory should contain `.verdict` files for `e4_stock_*`, `e4_lhr_*`, `ems_stock_*`, `ems_lhr_*`.

## Notes

- 172.16.0.100 / .101 are camera STAs, not adb addresses
- `adb` must be on PATH
- Do not use `run_board.ps1` (deprecated)
- A single peer only supports the EMS mismatch; it cannot support Claim-2's N-1 amplification on its own. Run two peers when a second camera is available.

## LHR overhead measurement

```bat
measure_overhead.bat
measure_overhead.bat 100
```

Results: `overhead_*.summary` (p50/p95 + duty-cycle) under `board_results\overhead_<timestamp>\`.
Send the summary back to buildserver to fill the paper's overhead table.
