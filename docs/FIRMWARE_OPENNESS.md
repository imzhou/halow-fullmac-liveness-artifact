# 泰芯 SDK 开放度评估（影响论文深度）

路径：`/home/zhoujifeng/code/wifi_halow/TX_AH_SDK_2.4/TXW8301_FMAC-v2.4.1.5-40938`

## 1. 闭源（论文里不能吹“改了 MAC 算法”）

| 库 | 大小 | 含义 |
|----|------|------|
| libwifi.a | 518 KB | WiFi/UMAC 主体 |
| liblmac.a | 474 KB | 802.11ah LMAC |
| libcore.a | 88 KB | 核心调度 |
| libcommon / libosal / libnetutils / libatcmd | 较小 | 公共/OSAL/网络/AT |

结论：**TX/MCS/RAW/exception 触发逻辑在 .a 里，源码不可改。**

## 2. 开源可改（真正的实验面）

| 层 | 文件 | 可做什么 |
|----|------|----------|
| 驱动 host | `hgicf.ko` 全源码 | 消费 exception/事件、恢复策略、soft_fc、carrier |
| 固件应用 | `project/main.c, events.c, syscfg.c, wakeup.c` | 睡眠钩子、配置、系统事件响应 |
| 总线 | `sdk/lib/bus/macbus/usb_bus.c` | USB 收发、pending、对齐、rxerr |
| AT | `project/atcmd.c` | 调试/触发接口 |
| 头文件契约 | `sdk/include/lib/lmac/hgic.h` | 完整 HGIC_EVENT / HGIC_EXCEPTION 枚举 |

固件已通过事件暴露（host 可见）：
- `HGIC_EVENT_EXCEPTION_INFO` + `HGIC_EXCEPTION_{CPU,HEAP,BUFFER,TX_BLOCKED,TXDELAY,BGRSSI,TEMP}`
- CONNECT/DISCONNECT/SIGNAL/ROAM/SLEEP 等

## 3. 对论文策略的硬约束

### 能写的（有源码支撑）
1. **Host 侧 exception 驱动的抢占恢复**（主推）  
   在 `hgicf.ko` / userspace 消费 `EXCEPTION_INFO`，在 netdev down 前动作。
2. **Android FMAC 故障刻画**（suspend/hg0 down/USB reinit）
3. **固件 sleep/wakeup 路径**（project 可改钩子 + host 观测）
4. **USB macbus 行为**（pending/对齐/rxerr）与 host soft_fc 交互
5. **配置面**（ps_mode/bss_bw/agg）对可靠性的影响——旋钮在，算法闭源也能测

### 不能写的（避免审稿打脸）
- “我们改进了 802.11ah LMAC 的重传/RAW/MCS 算法”
- “固件内部 exception 生成逻辑的优化”（.a 不可见）
- 把闭源行为当成自己的贡献

## 4. 修订后的 IoT-J 可行叙事（仍偏紧）

**Title 方向**  
*Host-Side Preemptive Recovery for Wi-Fi HaLow FullMAC Links:  
Exception-Aware Design on an Android Camera-Tablet Stack*

贡献三条改写为：
1. 在真实 FullMAC 产品栈上，量化 **exception 事件 → 最终 outage** 的提前量（lead time）——这是 measurement 洞察
2. 设计 **host 侧** 分级恢复（不用改闭源 LMAC）：  
   exception 降载 / 轻量 rebind / 延迟 reinit
3. 对比 stock（事后 rebind）与抢占方案的 outage/MTTR/误触发

固件源码的价值 = **看懂事件语义 + 改 project 钩子做可控注入**，  
而不是“重写 MAC”。

## 5. 深度够不够？更新判断

| 条件 | 现状 |
|------|------|
| 有 host 全源码 | ✅ |
| 有 exception 事件契约 | ✅ |
| 有真实产品与注入面 | ✅ |
| LMAC 可改 | ❌ |
| 摄像头源码 | ❌ |

→ **做穿“exception lead-time + host 抢占恢复 + 真机 N 次统计”仍有机会冲 IoT-J**；  
→ 若只能做到“介绍 SDK + 列故障 + 换 watch 脚本”，仍建议 **Access/Sensors**。

下一步实验优先级：
1. 在平板上 dump `fwevnt`/dmesg，确认 `HGIC_EVENT_EXCEPTION_INFO` 真的会到 host
2. 制造拥塞/干扰，测 exception 到 goodput 归零的 lead time
3. 再决定 LHR 是不是必须，还是把卖点全压在 lead-time + 抢占上