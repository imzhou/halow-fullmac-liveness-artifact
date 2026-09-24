# 实验计划（方向 C · IoT-J）

## 0. 前置
- [ ] 确认摄像头在线且已关联 hg0（hgpriv hg0 get sta_list 或 dnsmasq leases）
- [ ] 平板能 ping 通 172.16.0.x
- [ ] 打开可重复日志：/proc/hgicf/status 周期采样 + dmesg
- [ ] 无真码流时：对端或本机 iperf3 -u -b 300k 模拟上行/下行

## 1. 指标定义

| 指标 | 定义 |
|------|------|
| **Outage** | 应用 goodput 连续 =0 的时长（或 ping loss 连续窗口） |
| **MTTR** | 故障注入完成 → goodput 恢复到故障前 80% 的时间 |
| **Recovery rate** | 30 次注入中，120s 内恢复次数 / 30 |
| **False recovery** | 无故障时被 LHR 误触发 reinit/rebind 次数 |
| **Reinit count** | detect 触发 bus->reinit 次数 |
| **Session survival** | 拉流会话是否无需用户重启（1/0） |

采样：1s 粒度；关键路径打 kmsg 时间戳。

## 2. 注入矩阵（优先 P0）

| ID | 故障 | 注入方式 | 期望观测 |
|----|------|----------|----------|
| **P0-1** | resume 后 hg0 down | echo mem > /sys/power/state 或屏灭休眠再唤醒 | flags bit0=0；watch rebind |
| **P0-2** | 模拟固件 hang | 不可靠：可尝试不拔 USB 但停止响应；或短时 ifconfig hg0 down/up + 塞满 soft_fc | detect_tmr → reinit |
| **P0-3** | USB 重枚举 | 有权限则 unbind/bind USB 设备节点 | reinit + 网卡重建 |
| **P0-4** | 强干扰/邻道 | 共信道设备或扫频 | TXDELAY / 吞吐塌陷 |
| P1 | STA 掉电再上电 | 摄像头断电 5–30s | DISCONNECT 事件、恢复关联 |
| P1 | property 卡死 | 手动停 halow_net_watch | 对比有无 watch |
| P2 | 事件风暴 | 频繁 connect/disconnect | evt_list 溢出 |

## 3. 基线

| 代号 | 配置 |
|------|------|
| B0 | 现网 stock（watch + rebind） |
| B1 | 仅 naive：注入后手动 ip link set up + addr replace，无事件协同 |
| LHR | 本文机制（实现后替换） |

## 4. 每组实验协议

1. 预热 60s，记录 baseline goodput G0  
2. 注入故障，记 t0  
3. 监测至恢复或超时 120s，记 t1  
4. 冷却 30s，重复 N=30（至少 N=10 起步）  
5. 导出：outage = t1-t0；是否 session survived  

## 5. 表格模板

### T1 故障 × 机制 对比
| Fault | Metric | B0 | B1 | LHR |
|-------|--------|----|----|-----|
| P0-1 | MTTR mean/p95 | | | |
| P0-1 | Outage mean | | | |
| P0-1 | Recv rate % | | | |
| ... | ... | | | |

### T2 开销
| 方案 | CPU% | 额外包/s | False recovery / 10min |
|------|------|----------|-------------------------|
| B0 | | | |
| LHR | | | |

## 6. 最小可发表集（时间不够时）
只做 **P0-1 + P0-3 + 一种流量**，N=20，出 CDF + T1。  
再补 P0-2 或 STA 掉电加强故事。

## 7. 板端命令速查
\\\sh
# 状态
cat /proc/hgicf/status
hgpriv hg0 get signal
hgpriv hg0 get conn_state
# 链路
ip link show hg0
ping -c 5 172.16.0.x
# 日志
dmesg | tail
logcat -b all | grep -iE 'halow|hg0|hgic'
\\\
