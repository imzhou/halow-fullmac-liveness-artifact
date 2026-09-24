# Cross-layer control-plane liveness report (firmware + host + USB bus)

Model source: TaiXin TXW8301 FMAC SDK `TXW8301_FMAC-v2.4.1.5-40938`

| State variable | Meaning | Code evidence |
|----------------|---------|---------------|
| `ready` | Firmware to host uplink path usable | `usb_bus.c:32,79,86,103,128` |
| `pending` | Inbound data waiting for retry on the firmware side | `usb_bus.c:31,138` |
| `pd_age` | pending has aged out (>100 jiffies) | `usb_bus.c:46` |
| `fwq` | Firmware event queue occupancy (full level = 2, actual 32) | `main.c:419` |
| `hq` | Host event queue occupancy (full level = 2, actual 16) | driver `evt_list` |
| `dr` | Firmware has drop notifications owed to the host (introduced by the repair) | (none) |
| `aware` | Host has noticed the fault and can trigger recovery | (none) |
| `link` | Video session genuinely connected | (none) |

Liveness goal `GOOD(link=1 & fwq=0 & hq=0 & pending=0)`: session connected and both queues drained. (The released script labels this `GOOD`; the paper calls it `STREAMING`.)

Check semantics: adversarial environment, fair system. ENV actions are driven by the environment and not guaranteed to happen, so they do not count as escape paths; SYS/LHR actions are system-driven and, under fair scheduling, do run, so they do count. A state set the system can never escape (a trap set) then decides the verdict. This is much stricter than "some path recovers" (exists-eventually), which is too weak to support a "permanent outage" claim.

## 1. Scale of liveness violations

| Variant | Reachable states | Trap set | Share | Verdict |
|---------|------------------|----------|-------|---------|
| stock (as shipped) | 213 | 9 | 4.2% | Violates |
| Full repair (P+R+V1+V2) | 426 | 0 | 0.0% | Holds |

## 2. Stock counterexamples (shortest trigger paths)

| # | State | Depth | Trigger path |
|---|-------|-------|--------------|
| 1 | `ready=0 pending=0 pd_age=0 fwq=1 hq=0 dr=0 aware=0 link=0` | 2 | INIT -> `usb_tx_fail` -> `session_break` |
| 2 | `ready=0 pending=0 pd_age=0 fwq=0 hq=0 dr=0 aware=0 link=0` | 3 | INIT -> `usb_tx_fail` -> `session_break` -> `fw_flush_drop` |
| 3 | `ready=0 pending=0 pd_age=0 fwq=2 hq=0 dr=0 aware=0 link=0` | 3 | INIT -> `fw_evt` -> `usb_tx_fail` -> `session_break` |
| 4 | `ready=0 pending=1 pd_age=0 fwq=1 hq=0 dr=0 aware=0 link=0` | 3 | INIT -> `usb_tx_fail` -> `rx_enomem` -> `session_break` |
| 5 | `ready=0 pending=1 pd_age=0 fwq=0 hq=0 dr=0 aware=0 link=0` | 4 | INIT -> `usb_tx_fail` -> `rx_enomem` -> `session_break` -> `fw_flush_drop` |
| 6 | `ready=0 pending=1 pd_age=0 fwq=2 hq=0 dr=0 aware=0 link=0` | 4 | INIT -> `fw_evt` -> `usb_tx_fail` -> `rx_enomem` -> `session_break` |
| 7 | `ready=0 pending=1 pd_age=1 fwq=1 hq=0 dr=0 aware=0 link=0` | 4 | INIT -> `usb_tx_fail` -> `rx_enomem` -> `pd_poll_fail` -> `session_break` |
| 8 | `ready=0 pending=1 pd_age=1 fwq=0 hq=0 dr=0 aware=0 link=0` | 5 | INIT -> `usb_tx_fail` -> `rx_enomem` -> `pd_poll_fail` -> `session_break` -> `fw_flush_drop` |
| 9 | `ready=0 pending=1 pd_age=1 fwq=2 hq=0 dr=0 aware=0 link=0` | 5 | INIT -> `fw_evt` -> `usb_tx_fail` -> `rx_enomem` -> `pd_poll_fail` -> `session_break` |

All 9 counterexamples sit in the trap set. They are not just "one bad path exists"; they form a closed region. Once inside, no environment evolution and no scheduling can bring the system back. This is liveness violation in the strongest sense.

## 3. The core deadlock: a cross-layer dependency cycle

Deadlock state:

```
  ready=0 pending=0 pd_age=0 fwq=0 hq=0 dr=0 aware=0 link=0
```

Shortest trigger path:

```
  INIT
  usb_tx_fail
  session_break
  fw_flush_drop
```

Mechanism: four conditions presuppose each other and close a loop.

1. The only way `ready` returns to 1 is host-side downlink data triggering `USB_EP_RX_IRQ` (`usb_bus.c:128`).
2. Host downlink keeps flowing only while the session is healthy (`link=1` gives TCP ACKs / RTSP keepalives).
3. Session recovery needs the host to notice the fault, and noticing depends on firmware uplink events reaching `hq`.
4. Events reach `hq` only when `ready=1`.

Once `ready=0` and `link=0` hold at the same time, all four prerequisites fail together.

Worth stressing: each side's implementation is reasonable on its own. The firmware marks the path unusable after a failed write and only confirms it usable when host data arrives; the host treats the link as fine when no events arrive and sends nothing. The failure is in the composition, not in either side.

## 4. Drop without a trace: why operations cannot see it

| Drop point | Code | Trace |
|------------|------|-------|
| Uplink drop on `!ready` | `usb_bus.c:79-82` | Only `txerr++`, firmware-internal, invisible to the host |
| Write failure clears the ready bit | `usb_bus.c:86,103` | No event, no interrupt |
| Inbound timeout drop | `usb_bus.c:46,53-56` | No counter; `rxcount=0` and re-arm |
| Host queue full drop | driver `evt_list` full | No cumulative counter; `/proc/hgicf/status` shows only the current length |

All four agree on one thing: no retransmission after a drop. The firmware does know these failure states: `HGIC_EXCEPTION_TX_BLOCKED` / `TXDELAY_TOOLONG` / `WIFI_BUFFER_USED_OVERTOP` / `HEAP_USED_OVERTOP` / `CPU_USED_OVERTOP` (`hgic.h:287-295`), and `HGIC_EVENT_EXCEPTION_INFO = 27` (`hgic.h:276`) is a ready-made channel. Reporting, however, also travels over the same `ready` uplink. The channel exists; the path does not.

## 5. A heartbeat already exists, pointing the wrong way

`usb_bus.c:196` calls `usb_device_wifi_auto_tx_null_pkt_enable()` at init, which enables automatic null packets on `USB_WIFI_TX_EP` (device to host). Breaking the deadlock needs downlink from the host to the firmware (`USB_EP_RX_IRQ`). The same layer already has a heartbeat, in the opposite direction, so it does not cover this deadlock.

## 6. Repair ablation, item by item

| Configuration | Reachable states | Trap set | Verdict |
|---------------|------------------|----------|---------|
| stock (no repair) | 213 | 9 | Violates (9) |
| P only: periodic downlink heartbeat (recovers `ready` only) | 216 | 6 | Violates (6) |
| R only: periodic active query reconciliation | 213 | 0 | Holds |
| V1 only: uplink drops recorded for later report | 423 | 15 | Violates (15) |
| V2 only: inbound drops recorded for later report | 426 | 18 | Violates (18) |
| V1+V2: visibility only, no path repair | 423 | 15 | Violates (15) |
| P+V1+V2: heartbeat plus visibility, no query | 426 | 0 | Holds |
| P+R+V1+V2 (full) | 426 | 0 | Holds |

Three facts fall out:

1. A pure heartbeat (P) is not enough (6 trap states remain). It recovers the uplink path, but already-dropped events are not resent: `usb_bus.c:53-56` drops, sets `rxcount=0`, and re-arms, with no retransmission anywhere in the firmware. The path works again; the information is gone.
2. Visibility alone (V1/V2) is not enough (V1 leaves 15, V1+V2 leaves 15). Making drops visible means sending a notification up, and that notification travels over the broken path. Visibility parasitizes the very thing it is supposed to fix.
3. Active query reconciliation (R) alone removes every violation. One downlink does two jobs: it recovers `ready` and actively pulls back the true state, without relying on the firmware reporting first.

Two transferable design principles:

> **Principle 1 (path decoupling):** the liveness of a control-plane recovery path must not depend on the health of the object being recovered. Here the recovery of `ready` depends on host downlink, and continued host downlink depends on session health. The recovery action parasitizes its target, which necessarily produces liveness counterexamples.

> **Principle 2 (pull over push):** on a channel that drops without a trace and never retransmits, push-style state sync necessarily loses information. Recovery must use pull-style reconciliation.

Principle 1 is isomorphic to out-of-band management in distributed systems: if the management plane shares a path with the plane it manages, it dies with that path.

The query ability R needs already exists and is unused: `iwpriv sta_count` / `sta_list` read the STA table directly, but `halow_net_watch.sh` only looks at bit 0 of the netdev flags and has never called it.

## 6.5 Complete characterization of minimal repair sets (verified in the model)

The 8 configurations above hint at a stronger rule. Stated as a proposition and checked against all 16 subsets:

> **Proposition:** a repair subset S removes the deadlock if and only if S provides path liveness (`P in S` or `R in S`) **and** S provides state retrieval (`R in S` or `V1 in S`).

The right conjunct excludes V2 on purpose: the deadlock loop runs through the uplink drop path (`fw_flush_drop`), and only V1 covers it. V2 covers the inbound timeout drop (`pd_drop`), which is not part of this loop. A repair must cover the drop that causes the deadlock, not any drop in general.

| Subset S | Path liveness | State retrieval | Trap set | Actually effective | Proposition predicts | Match |
|----------|---------------|-----------------|----------|--------------------|-----------------------|-------|
| `(none)` | no | no | 9 | no | no | yes |
| `P` | yes | no | 6 | no | no | yes |
| `R` | yes | yes | 0 | yes | yes | yes |
| `V1` | no | yes | 15 | no | no | yes |
| `V2` | no | no | 18 | no | no | yes |
| `PR` | yes | yes | 0 | yes | yes | yes |
| `PV1` | yes | yes | 0 | yes | yes | yes |
| `PV2` | yes | no | 2 | no | no | yes |
| `RV1` | yes | yes | 0 | yes | yes | yes |
| `RV2` | yes | yes | 0 | yes | yes | yes |
| `V1V2` | no | yes | 15 | no | no | yes |
| `PRV1` | yes | yes | 0 | yes | yes | yes |
| `PRV2` | yes | yes | 0 | yes | yes | yes |
| `PV1V2` | yes | yes | 0 | yes | yes | yes |
| `RV1V2` | yes | yes | 0 | yes | yes | yes |
| `PRV1V2` | yes | yes | 0 | yes | yes | yes |

All 16 rows match, so the proposition holds inside the model. The minimal solutions are `['R', 'PV1']`, one or two actions in size.

This proposition is stronger than "every repair is necessary". Instead of listing one working fix, it characterizes the full set of working fixes with both necessary and sufficient conditions. A reviewer cannot wave it away with "maybe some other repair works too", because all 16 combinations are exhausted.

## 7. Conclusions

1. The cross-layer deadlock is reachable and holds under the strong liveness semantics: `usb_tx_fail` -> `session_break` -> `fw_flush_drop` enters the trap set, and no environment evolution brings it back.
2. The mechanism is compositional. Both implementations are reasonable alone; the deadlock comes from the loop "uplink recovery depends on downlink" and "continued downlink depends on session health".
3. It transfers. The structure depends on no private detail of TaiXin or A133. Any FullMAC module with a polling host stack reproduces it.
4. The repair is minimal and necessary: periodic active query (one USB downlink plus state retrieval) removes every violation. Pure heartbeat and pure visibility are both insufficient, and the existing null-packet mechanism (`usb_bus.c:196`) points the wrong way to help.
5. The diagnostic information already existed. `hgic.h:287-295` defines 8 exception classes and `hgic.h:276` provides the reporting channel. The observability gap is not that the information does not exist; it is that the information is generated but cannot travel the path.
