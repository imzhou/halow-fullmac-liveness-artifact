# Multi-STA scenario: session-level liveness report

> Model: `models/multi_sta_model.py`. Deployment: A133 tablet = HaLow AP, N cameras = STAs.

## 1. Scale of liveness violations per N

Counterexamples fall into two causes:

- **Loss type**: events dropped at `event.c:68-71`, so knowledge diverges from reality. Specific to multi-STA and the core of this model.
- **Reinit type**: firmware reinit wipes the STA table (`n_known=0`) while the real STAs are still on the air.

| Cameras N | Reachable states | Liveness violations | Share | Loss type | Reinit type | Shortest loss-type trigger |
|-----------|------------------|---------------------|-------|-----------|-------------|----------------------------|
| 2 | 153 | 68 | 44.4% | 34 | 34 | `sta_leave` -> `fw_reinit` -> `sta_join` |
| 4 | 425 | 272 | 64.0% | 204 | 68 | `sta_leave` -> `fw_reinit` -> `sta_join` |
| 8 | 1377 | 1088 | 79.0% | 952 | 136 | `sta_leave` -> `fw_reinit` -> `sta_join` |
| 12 | 2873 | 2448 | 85.2% | 2244 | 204 | `sta_leave` -> `fw_reinit` -> `sta_join` |
| 16 | 4913 | 4352 | 88.6% | 4080 | 272 | `sta_leave` -> `fw_reinit` -> `sta_join` |
| 20 | 7497 | 6800 | 90.7% | 6460 | 340 | `sta_leave` -> `fw_reinit` -> `sta_join` |
| 24 | 10625 | 9792 | 92.2% | 9384 | 408 | `sta_leave` -> `fw_reinit` -> `sta_join` |

> The violation share climbs monotonically with N (44% to 92%): more cameras make it easier for the control plane to enter a state it cannot heal. The curve is itself a scalability result, and it costs no extra hardware. The model alone yields it.

## 2. Core result under stock

At N=8: 1377 reachable states, **1088** of which violate session-level liveness.

Shared trait of the counterexamples: `n_assoc > 0` and `n_known != n_assoc`. The cameras are online, but what the AP believes diverges from reality.

### Why it cannot return

- `evt_drain` only consumes the queue; it never corrects a knowledge divergence that already formed (dropped events leave no trace; `procfs.c:34` shows only the current length).
- `fw_reinit` wipes the STA table (`n_known=0`) while the cameras are still on the air, so the divergence becomes `n_assoc` and gets larger.
- The rebind in `init.rc:62-69` only does L3/L4 `ip link up` + `addr replace`. It never touches the driver STA table.
- `halow_net_watch.sh:23` only looks at `flags & 1` and never queries `sta_count` (`iwpriv.c:1739` provides it).

### Smallest counterexample: `sta_leave` -> `fw_reinit` -> `sta_join`

This is the shortest counterexample for every N from 2 to 24, three steps, and every step happens in practice:

| Step | Action | n_assoc | n_known | What happens |
|------|--------|---------|---------|--------------|
| 0 | Initial | N | N | All N cameras online, knowledge matches |
| 1 | `sta_leave` | N-1 | N-1 | One camera drops, event queued, knowledge still in sync |
| 2 | `fw_reinit` | N-1 | 0 | Driver triggers firmware reinit, STA table wiped |
| 3 | `sta_join` | N | 1 | That camera returns, producing a CONNECTED event |

Step 3 is the crux. The other N-1 cameras never left. They still believe they are associated, so they never re-associate and never produce events. Their records were erased in step 2. The AP now knows one camera forever, and the other N-1 sessions die silently.

> The recovery mechanism itself creates the worse failure. The reinit the driver performs to heal itself turns "one camera dropped" into "N-1 cameras permanently gone". The amplification factor is N-1.

This counterexample needs no dropped events and no queue overflow. One reinit is enough, and `detect_work` at `core.c:872-880` triggers reinit whenever the firmware probe fails.

### Divergence stickiness (provable property)

Let `d = n_known - n_assoc`. Without event loss, `sta_join`/`sta_leave` move both sides by the same step, so d is unchanged. With event loss, d drifts in one direction. Therefore:

> Once d != 0 appears, d does not shrink, except through the uncontrolled coincidence of dropping one more event with the opposite sign.

Counting on the camera's spontaneous reconnect as a recovery mechanism is wrong. Reconnect events can be dropped too, and d is sticky under join/leave, so a reconnect does not cancel an existing divergence.

## 3. Event loss under bursty disassociation (queueing)

N cameras disassociating at once (AP restart, radio outage, mass power cut) produce N events instantly. Queue capacity is 16 (`event.c:26`) and the oldest is dropped (`event.c:68-71`):

| N | Lost with empty queue | With 4 backlogged | With 8 backlogged | Consequence |
|---|----------------------|-------------------|-------------------|-------------|
| 4 | 0 | 0 | 0 | No loss |
| 8 | 0 | 0 | 0 | No loss |
| 12 | 0 | 0 | 4 | Loss only with a deep backlog |
| 16 | 0 | 4 | 8 | No loss at idle, loss with backlog |
| 20 | 4 | 8 | 12 | Stale entries guaranteed, at least one camera permanently out |
| 24 | 8 | 12 | 16 | Stale entries guaranteed, at least one camera permanently out |

> The threshold: above N = 16, one network-wide reconnect necessarily drops events. This is not a probability question but a hard capacity constraint. Every dropped DISCONNECTED/CONNECTED corresponds to a permanent state divergence for one camera.

## 4. Comparison after the LHR repair

| N | Stock liveness violations | LHR liveness violations |
|---|---------------------------|-------------------------|
| 2 | 68 | 0 |
| 4 | 272 | 0 |
| 8 | 1088 | 0 |
| 12 | 2448 | 0 |
| 16 | 4352 | 0 |
| 20 | 6800 | 0 |
| 24 | 9792 | 0 |

LHR adds exactly one action: periodically query `iwpriv sta_count` and reconcile against the true online count (`LHR-A3`). The cost is one iwpriv command and no driver change.

## 5. What this adds to the paper

1. Counterexamples upgrade from "whole-port outage" to "permanent loss of individual sessions". Interface-level flags/IP/packet-loss all look normal, N-1 cameras stream fine, only the k-th is permanently dead. No interface-level watchdog can detect this.
2. A hard capacity threshold. Above N = 16 a single network-wide reconnect is necessarily inconsistent. `evt_list=16` turns from an implementation detail into a scalability constraint, which is the queueing entry point for the real-scalability angle.
3. The asymmetry of observability is nailed down. STA state is technically queryable (`sta_list`/`sta_count`), but the existing recovery chain never uses it, and dropped events leave no counter. The observability claim sharpens from "not enough information" to "the information exists but is not collected, and the loss is not traceable".
4. The repair is cheap. One iwpriv query makes session-level liveness hold, with no driver change. High impact at low cost is a good selling point.
