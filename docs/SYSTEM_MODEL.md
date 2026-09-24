# System model and fault taxonomy (with code evidence)

## 1. Deployment topology

```
[Camera STA] --802.11ah / ~866 MHz / 2 MHz BW--> [A133 Tablet AP]
   TaiXin TXW8301 USB                     USB TXW8301 + hgicf.ko (FullMAC)
   black box: associated STA only         netdev hg0  172.16.0.1/24
                                          Android 10 property state machine
                                          dnsmasq DHCP
                                          video playback
```

Production parameters (init.device.rc):

```
mode=ap  bss_bw=2  chan_list=8660  ps_mode=4  ap_psmode=1  dcdc13=1  tx_mcs=255
```

## 2. Vertical layers (recovery has to cross these)

| Layer | Implementation | Failure behavior |
|-------|----------------|------------------|
| L1 USB/bus | `utils/if_usb.c` bulk URB | urb fail, DMA alignment, unplug |
| L2 FMAC driver | `hgicf.ko` core/ctrl/event | `soft_fc` stalls TX, detect/reinit, queue drops |
| L3 firmware MAC | TXW8301 FW | hang, exception, failed sleep command |
| L4 Linux netdev | hg0 flags/carrier | admin DOWN, no IP |
| L5 Android | init property + watch | missed rebind trigger, cooldown effects |
| L6 Application | streaming session | stutter, slow first frame, dead session |

## 3. Fault taxonomy (paper Fig. 1)

### F1: power and sleep path

- F1a: after suspend hg0 stays IFF_UP but the firmware sleeps, creating a data black hole
- F1b: after resume hg0 goes admin DOWN (seen in the product); `halow_net_watch` polls every 5 s
- F1c: once `HGIC_BUS_FLAGS_SLEEP` is set, TX is blocked for the whole card (`core.c`), with no traffic distinction

### F2: firmware health / reinit

- `detect_timer` = 2 s; no response leads to a bootdl probe, then `bus->reinit` and firmware re-download
- Streaming necessarily stops during the reinit window (hundreds of ms to several s)
- TX failure also triggers `detect_work` (fast module reset)

### F3: software flow control

- `soft_fc` (fw < 0x2000000) with tx window = 20
- When the window is exhausted the driver spins in `msleep(10)`; video bursts can starve control frames

### F4: event-plane loss

- `evt_list` max = 16, oldest events dropped when full (`event.c`)
- Key events (CONNECTED / DISCONNECTED / EXCEPTION / SLEEP_FAIL) can be pushed out

### F5: Android integration

- Property chain: `hgicf.ready` to `hgpriv_done` to `setup_net` to `ready`
- dnsmasq stdin EOF caused 100% CPU (now wrapped with a fifo)
- rebind cooldown = 10 s can mask short faults or misfire

### F6: air interface / adjacent channel

- 2 MHz narrow band, adjacent LoRa or other HaLow
- Exceptions: `STRONG_BGRSSI` / `TXDELAY_TOOLONG`

## 4. Testable control knobs (independent variables)

| Knob | Interface | Use |
|------|-----------|-----|
| reinit policy | driver change / parameter | detect threshold, warm reset or not |
| rebind policy | watch script | period, threshold, idempotence |
| carrier handling | event CONNECT/DISCONNECT | timely `carrier_off`/`carrier_on` |
| event queue | size / priority | don't lose key events |
| `soft_fc` | can disable / tune window | less spinning |
| aggregation | `gg_cnt` | fewer small USB packets |

## 5. Baselines (paper Baseline)

- B0 Stock: factory driver plus the shipped `halow_net_watch` (product as-is)
- B1 Naive rebind: `ip link set hg0 up` + `addr replace` only (no carrier/event coordination)
- B2 This paper: layered recovery (see METHOD)

## 6. Mechanism of this paper (METHOD draft)

Layered HaLow Recovery (LHR):

1. Detect
   - driver: `detect_tmr` + exception events + `tx_fail`
   - userspace: hg0 flags, carrier, connectivity probe (lightweight UDP echo / DNS)
2. Classify
   - sleep-armed / fw-dead / netdev-down / app-session-dead
3. Act
   - L4: idempotent carrier and address handling
   - L5: property-triggered rebind (without cooldown side effects)
   - L2/L3: preserve session metadata across reinit; prefer warm recovery
4. Verify
   - post-recovery goodput probe plus first-packet latency; escalate to reinit on failure

Metric definitions live in [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md).
