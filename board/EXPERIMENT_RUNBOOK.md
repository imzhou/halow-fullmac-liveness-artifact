# 板端实验跑法（不编固件）

## 环境分工（必读）

| 机器 | 能力 |
|------|------|
| **本机 Windows** | `adb shell` 已通；跑 `scripts/windows/run_board.bat` |
| **buildserver** | 改论文/跑模型；**无 adb**；通过 **Z: 映射**读 `board_results/` |

不要在 buildserver 上执行 adb。详细步骤：[`windows/README.md`](windows/README.md)。

## Windows 一键（纯 bat）

默认套件每轮：`E4 stock` → `E4 LHR` → `EMS stock` → `EMS LHR`（`RUN_E2=0`）。

```bat
cd <Z: 上的>\iotj_C_reliability\scripts\windows
run_board.bat snap

REM 单摄像头：只验证 link-bounce mismatch（不支撑 Claim-2 的 N-1 放大）
run_board.bat 5 172.16.0.100

REM Claim-2：至少两台摄像头（N>=2）
run_board.bat 5 172.16.0.100 172.16.0.101
```

结果写入 `board_results\<时间戳>\`。详见 [`windows/README.md`](windows/README.md)。

## Claim 对齐

| 实验 | 需要 | 支撑 |
|------|------|------|
| E4 stock | 1 AP | oneshot watch 被杀后不自愈 |
| E4 LHR | 1 AP | pull/rebind 不依赖 oneshot watch 可恢复 |
| EMS stock / LHR（1 peer） | 1 摄像头 | alive vs `sta_count` 偏差 + LHR reconcile |
| EMS stock / LHR（≥2 peers） | ≥2 摄像头 | Claim-2：reinit / bounce 后 N−1 级会话偏差 |

`run_suite.sh` 在 `npeers<2` 时会打 WARN，但仍跑完单 peer 套件。

## buildserver 汇总

```bash
cd /home/zhoujifeng/code/SDK/paper/halow/iotj_C_reliability
python3 scripts/summarize_board_results.py board_results
```

## 判定

- `self_heal=0` E4 stock / EMS stock → 支持模型
- `self_heal=1` E4 LHR / EMS LHR → 支持修补
- `status=SKIP` E2 → 允许（不刷固件；sleep 可挂 FWCTRL）
