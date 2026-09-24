# hgpriv 命令速查（现网，不编固件）

接口：`hgpriv` → `/proc/hgicf/iwpriv`（见 `wifi_halow/tool/hgpriv.c`）。

格式：`hgpriv <ifname> <get|set> <name>[=args]`

## 论文必用

| 用途 | 命令 | 备注 |
|------|------|------|
| STA 数量 | `hgpriv hg0 get sta_count` | LHR-A3 / 跨层 R 的 pull 探针 |
| STA 列表 | `hgpriv hg0 get sta_list=1` | 二进制结构；脚本里可只信 count |
| 强制睡眠 | `hgpriv hg0 set sleep=<type>,<ms>` | E2；type/ms 需板端试；失败则标模型预测 |
| 自动睡时间 | `hgpriv hg0 set autosleep_time=<n>` | 辅助 |
| 信号 | `hgpriv hg0 get signal` | 健康基线 |
| 连接态 | `hgpriv hg0 get conn_state` | 健康基线 |

库函数对照（`iwpriv.c`）：

- `hgic_iwpriv_get_sta_count` → `sta_count`
- `hgic_iwpriv_get_sta_list` → `sta_list=1`
- `hgic_iwpriv_sleep` → `set sleep=<type>,<ms>`（`set_ints` 逗号分隔）

## 固件只读佐证（不编译）

路径：`~/code/wifi_halow/TX_AH_SDK_2.4/TXW8301_FMAC-v2.4.1.5-40938/`

| 证据 | 位置 | 用途 |
|------|------|------|
| `SYS_STA_MAX` 默认 8 / 可选 31 | `project/sys_config.h`, `project_config.h:25` | 多 STA 容量上界 |
| `ready` 置 0/1 | `sdk/lib/bus/macbus/usb_bus.c:86,103,128` | 跨层死锁 |
| 事件枚举 | `sdk/include/lib/lmac/hgic.h` | 与主机驱动对齐 |

## 观测旁路（非 hgpriv）

```sh
cat /sys/class/net/hg0/flags          # watch 只看 bit0
cat /proc/hgicf/status
getprop | grep halow
ip link show hg0
```
