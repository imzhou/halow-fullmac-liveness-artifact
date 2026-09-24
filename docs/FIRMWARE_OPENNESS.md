# TaiXin SDK openness assessment (what the paper can and cannot claim)

Path: `/home/zhoujifeng/code/wifi_halow/TX_AH_SDK_2.4/TXW8301_FMAC-v2.4.1.5-40938`

## 1. Closed source (don't claim "we changed the MAC algorithm")

| Library | Size | Role |
|---------|------|------|
| libwifi.a | 518 KB | Wi-Fi/UMAC body |
| liblmac.a | 474 KB | 802.11ah LMAC |
| libcore.a | 88 KB | Core scheduling |
| libcommon / libosal / libnetutils / libatcmd | smaller | Common / OSAL / network / AT |

Bottom line: TX/MCS/RAW/exception trigger logic lives in the .a files and cannot be modified.

## 2. Open source and modifiable (the real experimental surface)

| Layer | Files | What you can do |
|-------|-------|-----------------|
| Host driver | full `hgicf.ko` source | Consume exceptions/events, recovery policy, `soft_fc`, carrier |
| Firmware application | `project/main.c`, `events.c`, `syscfg.c`, `wakeup.c` | Sleep hooks, configuration, system event handling |
| Bus | `sdk/lib/bus/macbus/usb_bus.c` | USB TX/RX, pending, alignment, rxerr |
| AT | `project/atcmd.c` | Debug / trigger interface |
| Header contracts | `sdk/include/lib/lmac/hgic.h` | Full `HGIC_EVENT` / `HGIC_EXCEPTION` enums |

The firmware already surfaces these events to the host:

- `HGIC_EVENT_EXCEPTION_INFO` plus `HGIC_EXCEPTION_{CPU,HEAP,BUFFER,TX_BLOCKED,TXDELAY,BGRSSI,TEMP}`
- CONNECT/DISCONNECT/SIGNAL/ROAM/SLEEP and friends

## 3. Hard constraints on what the paper can say

### Supported by source (safe to write)

1. Host-side exception-driven preemptive recovery (the main claim): consume `EXCEPTION_INFO` in `hgicf.ko` or userspace and act before the netdev goes down.
2. Android FullMAC fault characterization (suspend / hg0 down / USB reinit).
3. Firmware sleep/wakeup path (modifiable project hooks plus host-side observation).
4. USB macbus behavior (pending / alignment / rxerr) and its interaction with host `soft_fc`.
5. Configuration surface (`ps_mode` / `bss_bw` / `agg`) effects on reliability: the knobs exist even though the algorithm is closed.

### Not supported (don't write these)

- "We improved the retransmission/RAW/MCS algorithm of the 802.11ah LMAC."
- "We optimized the firmware's internal exception generation logic" (invisible in the .a files).
- Presenting closed-source behavior as your own contribution.

## 4. Revised paper narrative (still tight)

Working title direction: *Host-Side Preemptive Recovery for Wi-Fi HaLow FullMAC Links: Exception-Aware Design on an Android Camera-Tablet Stack*

The three contributions, restated:

1. Quantify the lead time from exception event to final outage on a real FullMAC product stack. This is the measurement insight.
2. Design host-side graded recovery that does not touch the closed LMAC: exception-driven load shedding, light rebind, deferred reinit.
3. Compare stock (reactive rebind) with the preemptive scheme on outage, MTTR, and false triggers.

The value of the firmware source is understanding event semantics and adding project hooks for controlled injection, not rewriting the MAC.

## 5. Is that deep enough? Updated judgment

| Condition | Status |
|-----------|--------|
| Full host source | yes |
| Exception event contract | yes |
| Real product with injection surface | yes |
| LMAC modifiable | no |
| Camera source | no |

Exception lead time plus host preemptive recovery plus repeated device runs is enough for a strong systems paper. If it stays at "introduce the SDK, list faults, swap the watch script", the contribution is thin.

Next experiments, in order:

1. Dump `fwevnt`/dmesg on the tablet and confirm `HGIC_EVENT_EXCEPTION_INFO` actually reaches the host.
2. Create congestion/interference and measure the lead time from exception to goodput collapse.
3. Then decide whether LHR is necessary, or whether the lead-time and preemption angle carries the paper.
