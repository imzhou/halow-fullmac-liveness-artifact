# Related Work 矩阵（方向 A · 活性 / 产品栈）

## Gap 一句话
现有 HaLow 文献集中在 **传播实测 / RAW MAC / 能耗**；协议/驱动形式化工作不覆盖 **Android FullMAC 主机栈活性**；传统 WiFi 恢复文献不覆盖 USB IoT FullMAC + property/oneshot 集成。

## 矩阵

| 类别 | 代表工作 | 做了什么 | 与本文差 |
|------|----------|----------|----------|
| HaLow 实测 | Maudet 2023/2024; Aust CCNC'24; Chounos 2025; Hakim 2025; Xu arXiv'26 | 距离/吞吐/能耗/监控场测 | 无 host 控制面活性 |
| HaLow MAC/RAW | Ahmed IoT-J 2021 survey; Guedes 2026 RAW survey | RAW/分组理论与仿真 | 非产品 FullMAC 故障 |
| 协议模型检验 | Holzmann SPIN; Lamport TLA+; wireless protocol MC 系列 | 协议正确性 | 不针对 Android+USB FMAC 组合 |
| Linux WiFi 恢复 | cfg80211 reconnect / rfkill 实践与内核文档 | SoftMAC 重连 | 非 HaLow USB FullMAC |
| Android 网络可用性 | 2.4/5G WiFi 可用性、doze 研究 | 非 802.11ah 模组栈 | 频段与驱动模型不同 |
| 分布式 out-of-band 管理 | 经典带外管理 / 控制面与数据面分离 | 原则同构 | 本文给出 HaLow USB `ready` 实例 |

## 参考文献（草稿 Bib 条目，投稿前用正式 .bib 核对）

1. IEEE Std 802.11ah-2016 (HaLow).
2. Ahmed et al., “MAC protocols for IEEE 802.11ah-based IoT,” IEEE IoT-J, 2021.
3. Maudet et al., “Practical evaluation of Wi-Fi HaLow,” Internet of Things, 2023.
4. Maudet et al., energy consumption, IEEE IoT-J, 2024.
5. Kane et al., HaLow vs LoRa, Sensors, 2023.
6. Chounos et al., 802.11ah testbed, 2025.
7. Guedes et al., RAW survey, Wireless Networks, 2026.
8. Hakim et al., HaLow surveillance LOS/NLOS, 2025.
9. Xu et al., long-range monitoring, arXiv, 2026.
10. Holzmann, *The SPIN Model Checker*.
11. Lamport, *Specifying Systems* (TLA+).
12. Linux wireless / cfg80211 documentation (reconnect paths).

## 投稿定位句
> Unlike prior HaLow studies that characterize PHY/MAC performance on SoftMAC modules or simulations, we prove **liveness failures** of a commercial USB FullMAC + Android host control plane, and validate self-heal boolean outcomes on device without custom firmware.
