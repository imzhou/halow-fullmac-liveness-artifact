# Board experiment runbook (no firmware rebuild)

## Who runs what (read first)

| Machine | Role |
|---------|------|
| Local Windows | `adb shell` works; run `board/windows/run_board.bat` |
| buildserver | Paper edits and models; no adb; reads `board_results/` through the Z: mount |

Do not run adb on buildserver. Step-by-step detail: [windows/README.md](windows/README.md).

## One-shot Windows run (pure .bat)

The default suite runs E4 stock, E4 LHR, EMS stock, EMS LHR per round (`RUN_E2=0`).

```bat
cd <Z:>\board\windows
run_board.bat snap

REM single camera: only validates link-bounce mismatch (does not support Claim-2's N-1 amplification)
run_board.bat 5 172.16.0.100

REM Claim-2: at least two cameras (N>=2)
run_board.bat 5 172.16.0.100 172.16.0.101
```

Results land in `board_results\<timestamp>\`. See [windows/README.md](windows/README.md).

## Claim alignment

| Experiment | Needs | Supports |
|------------|-------|----------|
| E4 stock | 1 AP | No self-heal after the oneshot watch is killed |
| E4 LHR | 1 AP | Pull/rebind recovers without the oneshot watch |
| EMS stock / LHR (1 peer) | 1 camera | `alive` vs `sta_count` mismatch plus LHR reconcile |
| EMS stock / LHR (>=2 peers) | >=2 cameras | Claim-2: N-1 session mismatch after reinit / bounce |

`run_suite.sh` prints a WARN when `npeers<2` but still runs the single-peer suite.

## Aggregating on buildserver

```bash
cd <repo root>
python3 analysis/summarize_board_results.py data
```

## Reading the verdicts

- `self_heal=0` on E4 stock / EMS stock supports the model.
- `self_heal=1` on E4 LHR / EMS LHR supports the repair.
- `status=SKIP` on E2 is allowed (no firmware flash; sleep may hang FWCTRL).
