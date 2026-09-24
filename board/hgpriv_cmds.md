# hgpriv command cheatsheet (as shipped, no firmware rebuild)

Interface: `hgpriv` writes to `/proc/hgicf/iwpriv` (see `wifi_halow/tool/hgpriv.c`).

Format: `hgpriv <ifname> <get|set> <name>[=args]`

## Commands the paper needs

| Purpose | Command | Notes |
|---------|---------|-------|
| STA count | `hgpriv hg0 get sta_count` | The pull probe behind LHR-A3 and cross-layer R |
| STA list | `hgpriv hg0 get sta_list=1` | Binary struct; scripts can trust just the count |
| Force sleep | `hgpriv hg0 set sleep=<type>,<ms>` | E2; type/ms need board-side trial; if it fails, mark as model prediction |
| Auto-sleep time | `hgpriv hg0 set autosleep_time=<n>` | Auxiliary |
| Signal | `hgpriv hg0 get signal` | Health baseline |
| Connection state | `hgpriv hg0 get conn_state` | Health baseline |

Library mapping (`iwpriv.c`):

- `hgic_iwpriv_get_sta_count` to `sta_count`
- `hgic_iwpriv_get_sta_list` to `sta_list=1`
- `hgic_iwpriv_sleep` to `set sleep=<type>,<ms>` (`set_ints`, comma separated)

## Read-only firmware evidence (no build)

Path: `~/code/wifi_halow/TX_AH_SDK_2.4/TXW8301_FMAC-v2.4.1.5-40938/`

| Evidence | Location | Use |
|----------|----------|-----|
| `SYS_STA_MAX` defaults to 8, optional 31 | `project/sys_config.h`, `project_config.h:25` | Multi-STA capacity ceiling |
| `ready` set to 0/1 | `sdk/lib/bus/macbus/usb_bus.c:86,103,128` | Cross-layer deadlock |
| Event enums | `sdk/include/lib/lmac/hgic.h` | Aligned with the host driver |

## Observation side channels (not hgpriv)

```sh
cat /sys/class/net/hg0/flags          # the watch only looks at bit0
cat /proc/hgicf/status
getprop | grep halow
ip link show hg0
```
