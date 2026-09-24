# HaLow control-plane model checking report

> Model: `models/control_plane_model.py`. Method: exhaustive reachable state space plus backward reachability (liveness check).

## 0. Model size

- State variables: 11 (iface / sleep / fw / run / darm / watch / 3 properties / event queue / loss flag)
- Stock variant actions: 24 (including 9 fault injections)
- Reachable states: 1296
- Reachable transition edges: 9216
- Initial state: `iface=DOWN      sleep=0 fw=LIVE run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0`

## 1. Liveness check (stock = the implementation as shipped)

Reachable states that violate liveness (permanent outage): **972 / 1296 (75.0%)**

In other words, the stock control plane has a large set of reachable permanent-outage states. Once in one of them, no matter how the system runs by itself (with no human help), it never returns to normal streaming.

### 1.1 Shortest counterexamples (minimum action count from the initial state)

| # | Steps | State | Mechanism | Shortest trigger path |
|---|-------|-------|-----------|----------------------|
| 1 | 1 | `iface=DOWN      sleep=0 fw=LIVE run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | Watch never started + RUNNING=0 | `f_run_clear` |
| 2 | 1 | `iface=DOWN      sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | Watch never started + stuck SLEEP masks self-check + firmware unresponsive | `f_sleep_stuck` |
| 3 | 2 | `iface=ABSENT    sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | Interface gone + watch never started + stuck SLEEP masks self-check + firmware unresponsive | `f_usb_out` -> `f_sleep_stuck` |
| 4 | 2 | `iface=BLACKHOLE sleep=0 fw=LIVE run=1 darm=1 watch=WAIT   ready=1 reb=0 init=1 evtq=0 lost=0` | Data black hole (admin UP, has IP, no flow) + watch never started | `do_setup_net` -> `f_blackhole` |
| 5 | 2 | `iface=DOWN      sleep=0 fw=DEAD run=0 darm=0 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | Watch never started + RUNNING=0 + detect_tmr chain dead + firmware unresponsive | `f_fw_hang` -> `detect_reinit_fail` |
| 6 | 2 | `iface=DOWN      sleep=0 fw=DEAD run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | Watch never started + RUNNING=0 + firmware unresponsive | `f_fw_hang` -> `f_run_clear` |
| 7 | 2 | `iface=DOWN      sleep=0 fw=LIVE run=0 darm=0 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | Watch never started + RUNNING=0 + detect_tmr chain dead | `f_run_clear` -> `detect_disarm` |
| 8 | 2 | `iface=DOWN      sleep=0 fw=LIVE run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=1 lost=0` | Watch never started + RUNNING=0 | `evt_push` -> `f_run_clear` |
| 9 | 2 | `iface=DOWN      sleep=0 fw=LIVE run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=2 lost=1` | Watch never started + RUNNING=0 | `f_evt_burst` -> `f_run_clear` |
| 10 | 2 | `iface=DOWN      sleep=1 fw=DEAD run=0 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0` | Watch never started + stuck SLEEP masks self-check + RUNNING=0 + firmware unresponsive | `f_sleep_stuck` -> `f_run_clear` |
| 11 | 2 | `iface=DOWN      sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=1 lost=0` | Watch never started + stuck SLEEP masks self-check + firmware unresponsive | `evt_push` -> `f_sleep_stuck` |
| 12 | 2 | `iface=DOWN      sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=0 reb=0 init=0 evtq=2 lost=1` | Watch never started + stuck SLEEP masks self-check + firmware unresponsive | `f_sleep_stuck` -> `f_evt_burst` |

### 1.2 Counterexample mechanisms (counted over states)

| Mechanism | States |
|-----------|--------|
| RUNNING=0 | 720 |
| Firmware unresponsive | 702 |
| Stuck SLEEP masks self-check | 432 |
| detect_tmr chain dead | 360 |
| Watch exited (oneshot) | 324 |
| Watch never started | 216 |
| Interface gone | 216 |
| Data black hole (admin UP, has IP, no flow) | 216 |
| Watch thinks all is well (admin UP) | 42 |

### 1.3 Worked counterexamples

**Black-hole absorbing state** (3 steps):

```
  do_setup_net -> watch_start -> f_blackhole
  => iface=BLACKHOLE sleep=0 fw=LIVE run=1 darm=1 watch=POLL   ready=1 reb=0 init=1 evtq=0 lost=0
```

- Mechanism: data black hole (admin UP, has IP, no flow)
- Why it cannot return:
  - `halow_net_watch.sh:23` only checks `flags & 1`. The black-hole state is admin UP, so the loop `continue`s and the watch never sees it.
  - `core.c:861` `detect_work` only acts when `!SLEEP && fw unresponsive`. Here fw=LIVE, so no reinit fires.
  - Nothing else touches the datapath, so the black hole persists forever.

**SLEEP masks self-check** (3 steps):

```
  do_setup_net -> f_sleep_stuck -> f_blackhole
  => iface=BLACKHOLE sleep=1 fw=DEAD run=1 darm=1 watch=WAIT   ready=1 reb=0 init=1 evtq=0 lost=0
```

- Mechanism: data black hole (admin UP, has IP, no flow) + watch never started + stuck SLEEP masks self-check + firmware unresponsive
- Why it cannot return:
  - `core.c:861` `if (!SLEEP && RUNNING)`: with SLEEP set the whole check is skipped and only the timer is re-armed.
  - If the firmware sleeps to death, SLEEP never clears and the driver self-check spins forever.

**Watch exit** (3 steps):

```
  do_setup_net -> watch_start -> f_watch_exit
  => iface=UP_IP     sleep=0 fw=LIVE run=1 darm=1 watch=EXITED ready=1 reb=0 init=1 evtq=0 lost=0
```

- Mechanism: watch exited (oneshot)
- Why it cannot return:
  - `init.rc:57` registers `halow_net_watch` as a oneshot service; once it exits it is never restarted.
  - Nobody triggers rebind afterwards.

**Timer chain break** (2 steps):

```
  f_fw_hang -> detect_reinit_fail
  => iface=DOWN      sleep=0 fw=DEAD run=0 darm=0 watch=WAIT   ready=0 reb=0 init=0 evtq=0 lost=0
```

- Mechanism: watch never started + RUNNING=0 + detect_tmr chain dead + firmware unresponsive
- Why it cannot return:
  - `core.c:886` `if (RUNNING) mod_timer(...)`: with RUNNING=0 the timer is never re-armed and the self-check chain stops for good.

### 1.4 Steady-state single-fault counterexamples (headline result)

The statistics above mix in cold-start races. What the paper needs most is this class: the system is already streaming normally (`STREAMING`), a single fault is injected, and from then on it cannot heal itself.

- Reachable STREAMING states: 6
- Fault types that cause permanent outage from a single injection: **4 / 9**

| Fault injection | State after | Mechanism | Hard outage? |
|-----------------|-------------|-----------|--------------|
| `f_blackhole` | `iface=BLACKHOLE sleep=0 fw=LIVE run=1 darm=1 watch=POLL   ready=1 reb=0 init=1 evtq=0 lost=0` | Data black hole (admin UP, has IP, no flow) | Yes (datapath unusable at once) |
| `f_run_clear` | `iface=UP_IP     sleep=0 fw=LIVE run=0 darm=1 watch=POLL   ready=1 reb=0 init=1 evtq=0 lost=0` | RUNNING=0 + watch thinks all is well (admin UP) | No (capability loss: still streaming, but self-healing is gone) |
| `f_sleep_stuck` | `iface=UP_IP     sleep=1 fw=DEAD run=1 darm=1 watch=POLL   ready=1 reb=0 init=1 evtq=0 lost=0` | Stuck SLEEP masks self-check + firmware unresponsive + watch thinks all is well (admin UP) | Yes (datapath unusable at once) |
| `f_watch_exit` | `iface=UP_IP     sleep=0 fw=LIVE run=1 darm=1 watch=EXITED ready=1 reb=0 init=1 evtq=0 lost=0` | Watch exited (oneshot) | No (capability loss: still streaming, but self-healing is gone) |

- **Hard outage** (datapath unusable at once): 12 (fault, state) pairs
- **Capability loss** (still streaming, but recovery capability is gone; the next fault will kill it): 12 pairs

> Capability loss is the class this model is most worth emphasizing: the system looks completely normal, every monitoring light is green, yet it can no longer recover from any fault. Traditional availability measurements miss these states entirely. Uptime reads 100% while actual fragility is 100%.

## 2. Comparison: liveness after the LHR repair

- LHR variant actions: 29 (5 repair actions added)
- Reachable states: 1458
- Liveness violations: **0**

With the repair, liveness holds: under the same fault injection set, every reachable state returns to STREAMING without outside help (fault actions excluded).

This comparison closes the methodological loop for the paper. Stock has many permanent-outage states, LHR has zero, and the result is an exhaustive proof rather than sampled measurement.

## 3. Safety check (black-hole states)

- Reachable stock black-hole states: 216
- Of those, liveness violations: 216
- Conclusion: once a black-hole state is entered it is almost certainly not self-healing, because the observation plane only sees admin UP. The faults are indistinguishable.

## 4. What the paper takes from this

1. A provable negative result. The combination of polling, cooldown, one-way observation, and drop-oldest event queues produces a non-empty, sizable set of permanent-outage states in the reachable state space. This is a property of the design pattern and is independent of TaiXin/A133, which answers external-validity doubts head-on.
2. Transferable design principles. The four LHR repairs (datapath probe, detect not masked by SLEEP, timer guard, self-guarding watch) each map to one liveness counterexample class, and none is redundant.
3. The role of experiments changes. On-device injection is no longer the whole paper but a validation of the formal result: the model's counterexample paths are reproduced one by one on the board.
