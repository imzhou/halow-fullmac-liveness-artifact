# HaLow 控制面形式化检验报告

> 模型：`A/control_plane_model.py` ｜ 方法：穷举可达状态空间 + 反向可达性（活性检验）

## 0. 模型规模

- 状态变量：11 个（iface / sleep / fw / run / darm / watch / 3 个 property / 事件队列 / 丢失标记）
- stock 变体动作数：24（含 9 个故障注入）
- **可达状态数：1296**
- 可达转移边数：9216
- 初始状态：`iface=DOWN      sleep=0 fw=LIVE run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0`

## 1. 活性检验结果（stock = 现网实现）

**违反活性（永久断流）的可达状态：972 / 1296 （75.0%）**

也就是说：现网控制面**存在大量可达的永久断流状态**——从这些状态出发，无论系统自身如何运转（不借助人工外力），都回不到正常拉流。

### 1.1 最短反例（从初始状态出发需要的最少动作数）

| # | 步数 | 状态 | 机理 | 最短触发路径 |
|---|------|------|------|--------------|
| 1 | 1 | `iface=DOWN      sleep=0 fw=LIVE run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | 看门狗从未启动 + RUNNING=0 | f_run_clear |
| 2 | 1 | `iface=DOWN      sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | 看门狗从未启动 + SLEEP 卡死屏蔽自检 + 固件无响应 | f_sleep_stuck |
| 3 | 2 | `iface=ABSENT    sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | 接口消失 + 看门狗从未启动 + SLEEP 卡死屏蔽自检 + 固件无响应 | f_usb_out → f_sleep_stuck |
| 4 | 2 | `iface=BLACKHOLE sleep=0 fw=LIVE run=1 darm=1 watch=WAIT   ready=1 reb=0 init=1 evtq=0 lost=0` | 数据面黑洞（admin UP 但有 IP 无流） + 看门狗从未启动 | do_setup_net → f_blackhole |
| 5 | 2 | `iface=DOWN      sleep=0 fw=DEAD run=0 darm=0 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | 看门狗从未启动 + RUNNING=0 + detect_tmr 停摆 + 固件无响应 | f_fw_hang → detect_reinit_fail |
| 6 | 2 | `iface=DOWN      sleep=0 fw=DEAD run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | 看门狗从未启动 + RUNNING=0 + 固件无响应 | f_fw_hang → f_run_clear |
| 7 | 2 | `iface=DOWN      sleep=0 fw=LIVE run=0 darm=0 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | 看门狗从未启动 + RUNNING=0 + detect_tmr 停摆 | f_run_clear → detect_disarm |
| 8 | 2 | `iface=DOWN      sleep=0 fw=LIVE run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=1 lost=0` | 看门狗从未启动 + RUNNING=0 | evt_push → f_run_clear |
| 9 | 2 | `iface=DOWN      sleep=0 fw=LIVE run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=2 lost=1` | 看门狗从未启动 + RUNNING=0 | f_evt_burst → f_run_clear |
| 10 | 2 | `iface=DOWN      sleep=1 fw=DEAD run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | 看门狗从未启动 + SLEEP 卡死屏蔽自检 + RUNNING=0 + 固件无响应 | f_sleep_stuck → f_run_clear |
| 11 | 2 | `iface=DOWN      sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=1 lost=0` | 看门狗从未启动 + SLEEP 卡死屏蔽自检 + 固件无响应 | evt_push → f_sleep_stuck |
| 12 | 2 | `iface=DOWN      sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=2 lost=1` | 看门狗从未启动 + SLEEP 卡死屏蔽自检 + 固件无响应 | f_sleep_stuck → f_evt_burst |

### 1.2 反例机理归类（按状态特征统计）

| 机理 | 涉及状态数 |
|------|-----------|
| RUNNING=0 | 720 |
| 固件无响应 | 702 |
| SLEEP 卡死屏蔽自检 | 432 |
| detect_tmr 停摆 | 360 |
| 看门狗已退出(oneshot) | 324 |
| 看门狗从未启动 | 216 |
| 接口消失 | 216 |
| 数据面黑洞（admin UP 但有 IP 无流） | 216 |
| 看门狗认为一切正常(admin UP) | 42 |

### 1.3 典型反例详解

**黑洞吸收态** — 最短 3 步：

```
  do_setup_net → watch_start → f_blackhole
  ⇒ iface=BLACKHOLE sleep=0 fw=LIVE run=1 darm=1 watch=POLL   ready=1 reb=0 init=1 evtq=0 lost=0
```
- 机理：数据面黑洞（admin UP 但有 IP 无流）
- 为何回不去：
  - `halow_net_watch.sh:23` 只查 `flags & 1`，黑洞态 admin UP → `continue`，看门狗看不见
  - `core.c:861` detect_work 只在 `!SLEEP && fw 无响应` 时动作；此处 fw=LIVE，不触发 reinit
  - 于是**没有任何组件会改变数据面**，黑洞被永久保持

**SLEEP 屏蔽自检** — 最短 3 步：

```
  do_setup_net → f_sleep_stuck → f_blackhole
  ⇒ iface=BLACKHOLE sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=1 reb=0 init=1 evtq=0 lost=0
```
- 机理：数据面黑洞（admin UP 但有 IP 无流） + 看门狗从未启动 + SLEEP 卡死屏蔽自检 + 固件无响应
- 为何回不去：
  - `core.c:861` `if (!SLEEP && RUNNING)`：SLEEP 置位时整段检测被跳过，只重排定时器
  - 固件睡死 → SLEEP 永不清除 → 驱动自检永久空转

**看门狗退出** — 最短 3 步：

```
  do_setup_net → watch_start → f_watch_exit
  ⇒ iface=UP_IP     sleep=0 fw=LIVE run=1 darm=1 watch=EXITED ready=1 reb=0 init=1 evtq=0 lost=0
```
- 机理：看门狗已退出(oneshot)
- 为何回不去：
  - `init.rc:57` halow_net_watch 是 `oneshot` service，退出后不再重启
  - 此后无人再触发 rebind

**定时器链断裂** — 最短 2 步：

```
  f_fw_hang → detect_reinit_fail
  ⇒ iface=DOWN      sleep=0 fw=DEAD run=0 darm=0 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0
```
- 机理：看门狗从未启动 + RUNNING=0 + detect_tmr 停摆 + 固件无响应
- 为何回不去：
  - `core.c:886` `if (RUNNING) mod_timer(...)`：RUNNING=0 → 定时器不再装填 → 自检链永久停摆

### 1.4 稳态单次故障反例（headline 结论）

上面的统计混入了冷启动竞态。论文最需要的是这一类：**系统已经处于正常拉流（STREAMING），仅注入一次故障，此后系统再也无法自愈。**

- 可达的 STREAMING 状态数：6
- 能造成**单次故障即永久断流**的故障类型数：**4 / 9**

| 故障注入 | 注入后状态 | 机理 | 硬断流? |
|----------|-----------|------|---------|
| `f_blackhole` | `iface=BLACKHOLE sleep=0 fw=LIVE run=1 darm=1 watch=POLL   ready=1 reb=0 init=1 evtq=0 lost=0` | 数据面黑洞（admin UP 但有 IP 无流） | 是（数据面已不可用） |
| `f_run_clear` | `iface=UP_IP     sleep=0 fw=LIVE run=0 darm=1 watch=POLL   ready=1 reb=0 init=1 evtq=0 lost=0` | RUNNING=0 + 看门狗认为一切正常(admin UP) | 否（能力丧失：此刻仍在流，但已失去自愈能力） |
| `f_sleep_stuck` | `iface=UP_IP     sleep=1 fw=DEAD run=1 darm=1 watch=POLL   ready=1 reb=0 init=1 evtq=0 lost=0` | SLEEP 卡死屏蔽自检 + 固件无响应 + 看门狗认为一切正常(admin UP) | 是（数据面已不可用） |
| `f_watch_exit` | `iface=UP_IP     sleep=0 fw=LIVE run=1 darm=1 watch=EXITED ready=1 reb=0 init=1 evtq=0 lost=0` | 看门狗已退出(oneshot) | 否（能力丧失：此刻仍在流，但已失去自愈能力） |

- **硬断流**（数据面当场不可用）：12 个 (故障,状态) 组合
- **能力丧失**（此刻仍在拉流，但恢复能力已丢失，下次故障必断）：12 个组合

> 「能力丧失」是本模型最值得强调的一类：**系统当前看起来完全正常，监控指标全绿，但它已经不再具备从任何故障中恢复的能力**。这类状态在传统可用性测量中会被完全漏掉——uptime 是 100%，实际脆弱度是 100%。

## 2. 对照：LHR 修补后的活性

- LHR 变体动作数：29（新增 5 个修补动作）
- 可达状态数：1458
- **违反活性的状态：0**

✅ **修补后活性成立**：在同样的故障注入集合下，所有可达状态都能在不借助外力（不含故障动作）的前提下回到 STREAMING。

这条对比就是论文的方法学闭环：
stock 有大量永久断流状态 → LHR 为 0，且该结论是**穷举证明**而非抽样测量。


## 3. 安全性检验（黑洞态）

- stock 可达黑洞状态数：216
- 其中违反活性：216
- 结论：黑洞态一旦进入几乎必然不可自愈，因为观测面只见 admin UP，**故障不可区分**。

## 4. 对论文的产出

1. **否定结果（可证明）**：轮询 + 冷却 + 单向观测 + 丢旧事件队列这一组合，在可达状态空间中产生非空且规模可观的永久断流状态集。这是**设计模式的性质**，与泰芯/A133 无关，正面回应外部有效性质疑。
2. **可迁移设计原则**：LHR 的 4 条修补（数据面探针 / 检测不被 SLEEP 屏蔽 / 定时器守护 / 看门狗自守护）各自对应一类活性反例，缺一不可。
3. **实验角色转变**：真机注入实验不再是论文全部，而是对形式结论的**验证**——模型预测的反例路径，逐条在板端复现。
