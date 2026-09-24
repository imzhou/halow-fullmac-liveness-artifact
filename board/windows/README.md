# Windows 板端实验（纯 bat，无 PowerShell）

## 分工

| 环境 | 做什么 |
|------|--------|
| **本机 Windows** | `adb` + 双击/命令行跑 `run_board.bat` |
| **buildserver** | 读 `board_results/`，不跑 adb |

## 用法

在 Z: 上进入本目录后：

```bat
push_scripts.bat
restore_hg0.bat
run_board.bat snap

REM 默认套件：E4 stock + E4 LHR + EMS stock + EMS LHR（E2 关闭）
run_board.bat 5 172.16.0.100

REM Claim-2 多 STA：传 >=2 个摄像头 IP
run_board.bat 5 172.16.0.100 172.16.0.101
```

| 脚本 | 作用 |
|------|------|
| `push_scripts.bat` | 只 push `.sh` |
| `restore_hg0.bat` | 软恢复（up/IP/rebind） |
| `restore_halow_hard.bat` | **FWCTRL No Response 时用**：USB rebind + rmmod/insmod + 重新 setup |
| `run_board.bat` | push + 跑套件 + pull（含 E4 LHR；**默认不跑 E2**） |

E2（`hgpriv set sleep`）会把固件控通道打挂，已从默认套件移除。需要时：

```bat
adb shell "RUN_E2=1 N_REPEAT=1 sh /data/local/tmp/halow_exp/run_suite.sh /data/local/tmp/halow_exp 172.16.0.100"
```

| `run_board.bat` 参数 | 含义 |
|------|------|
| `snap` | 只拉 `snap_status` |
| 第一个数字 | 重复次数 N（默认 5） |
| 后续 IP | 摄像头 peers（**Claim-2 请给 ≥2 个**；默认 `172.16.0.100`） |
| `-s SERIAL` | 指定 adb 设备 |

结果：`iotj_C_reliability\board_results\<时间戳>\`

产出目录内应有 `e4_stock_*`、`e4_lhr_*`、`ems_stock_*`、`ems_lhr_*` 的 `.verdict`。

## 注意

- `172.16.0.100` / `.101` = 摄像头 STA，不是 adb 地址
- 需 `adb` 在 PATH
- 不要用 `run_board.ps1`（已弃用）
- 单 peer 只能支撑 EMS mismatch，**不能**单独支撑论文 Claim-2 的 N−1 放大；有第二台摄像头务必跑双 peer


## LHR 开销测量（R3-D）

```bat
measure_overhead.bat
measure_overhead.bat 100
```

结果：`board_results\overhead_<时间戳>\` 下的 `overhead_*.summary`（p50/p95 + duty-cycle）。
把 summary 发回 buildserver 即可填进论文 TBD 表。
