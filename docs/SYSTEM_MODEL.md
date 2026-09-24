# 系统模型与故障分类（代码证据版）

## 1. 部署拓扑

\\\
[Camera STA] --802.11ah / ~866 MHz / 2 MHz BW--> [A133 Tablet AP]
   泰芯 TXW8301 USB                         USB TXW8301 + hgicf.ko (FullMAC)
   黑盒：仅作关联 STA                        netdev hg0  172.16.0.1/24
                                             Android10 property 状态机
                                             dnsmasq DHCP
                                             拉流显示
\\\

生产参数（init.device.rc）：
\\\
mode=ap  bss_bw=2  chan_list=8660  ps_mode=4  ap_psmode=1  dcdc13=1  tx_mcs=255
\\\

## 2. 纵向分层（恢复要跨这些层）

| 层 | 实现 | 故障表现 |
|----|------|----------|
| L1 USB/总线 | utils/if_usb.c bulk URB | urb fail、DMA 对齐、拔插 |
| L2 FMAC 驱动 | hgicf.ko core/ctrl/event | soft_fc 停发、detect/reinit、队列丢弃 |
| L3 固件 MAC | TXW8301 FW | hang、exception、sleep 命令失败 |
| L4 Linux netdev | hg0 flags/carrier | admin DOWN、无 IP |
| L5 Android | init property + watch | rebind 漏触发、cooldown |
| L6 应用 | 拉流会话 | 卡顿、首帧慢、会话死 |

## 3. 故障分类 Taxonomy（论文 Fig.1）

### F1 电源/休眠路径
- **F1a** suspend 后 hg0 保持 IFF_UP，但固件睡眠，数据黑洞
- **F1b** resume 后 hg0 admin DOWN（产品已见）→ halow_net_watch 5s 轮询
- **F1c** HGIC_BUS_FLAGS_SLEEP 置位后 **整卡拦截 TX**（core.c），无区分业务

### F2 固件健康 / reinit
- detect_timer = 2s；无响应 → bootdl probe → us->reinit + 重下固件
- reinit 窗口内必然断流（百 ms～数 s）
- TX fail 亦触发 detect_work（快速检测模块复位）

### F3 软件流控
- soft_fc（fw < 0x2000000）+ tx window=20
- window 不足时 msleep(10) 空转；视频突发易饿死控制帧

### F4 事件面丢失
- evt_list max=16，满则丢旧事件（event.c）
- 关键事件：CONNECTED / DISCONNECTED / EXCEPTION / SLEEP_FAIL 可能被挤掉

### F5 Android 集成
- property 链：hgicf.ready → hgpriv_done → setup_net → ready
- dnsmasq stdin EOF → 100% CPU（已用 fifo wrap）
- rebind cooldown=10s，可能掩盖短故障或误判

### F6 空口/邻道
- 2 MHz 窄带、邻道 LoRa/其它 HaLow
- exception: STRONG_BGRSSI / TXDELAY_TOOLONG

## 4. 可测控制量（自变量）

| 旋钮 | 接口 | 用途 |
|------|------|------|
| reinit 策略 | 驱动改/参数 | 检测阈值、是否 warm reset |
| rebind 策略 | watch 脚本 | 周期、阈值、幂等 |
| carrier 处理 | event CONNECT/DISCONNECT | 及时 carrier_off/on |
| 事件队列 | 扩容/优先级 | 关键事件不丢 |
| soft_fc | 可关/调 window | 减少空转 |
| 聚合 | gg_cnt | 减少 USB 小包 |

## 5. 基线（论文 Baseline）

- **B0** Stock：原厂驱动 + 现网 halow_net_watch（产品现状）
- **B1** Naive rebind：仅 ip link set hg0 up + addr replace（无 carrier/事件协同）
- **B2** 本文：分层恢复（见 METHOD）

## 6. 本文机制（METHOD 草案）

**Layered HaLow Recovery (LHR)**

1. **Detect**
   - 驱动：detect_tmr + exception 事件 + tx_fail
   - 用户态：hg0 flags、carrier、连通性探针（轻量 UDP echo / DNS）
2. **Classify**
   - sleep-armed / fw-dead / netdev-down / app-session-dead
3. **Act**
   - L4：carrier 与 addr 幂等
   - L5：property 触发 rebind（去 cooldown 误伤）
   - L2/L3：reinit 时 **旁路保留会话元数据**；尽量 warm recovery
4. **Verify**
   - 恢复后 goodput 探针 + 首包延迟；失败升级 reinit

指标定义见 EXPERIMENT_PLAN。
