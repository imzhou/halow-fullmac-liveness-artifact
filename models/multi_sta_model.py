#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Session-level liveness checking for the multi-STA (multi-camera) scenario
========================================================================

Background
----------
Deployment: A133 tablet = HaLow AP (hg0, 172.16.0.1/24), N cameras = HaLow STAs.

This model focuses on a problem the single-STA model cannot see:

    **The STA table the AP keeps (n_known) and the number of STAs truly online
      on the air (n_assoc) can diverge permanently, and that divergence is
      completely invisible on the existing observation plane.**

Code evidence
-------------
1. AP-side association state can ONLY be learned from the firmware event stream:
   - `event.c:53-58` the `netif_carrier_on/off` calls for
     `HGIC_EVENT_CONECTED` / `DISCONECTED` are commented out -> the netdev layer
     does not reflect STA changes
   - `/proc/hgicf/` exports only status / ota / iwpriv / fwevnt (procfs.c:274-289),
     with no STA list file
2. The event stream loses events, and lost events leave no trace:
   - `event.c:26` HGIC_EVENT_MAX = 16
   - `event.c:68-71` queue full -> `skb_dequeue` drops the OLDEST
   - `/proc/hgicf/status` prints only the CURRENT length of `evt_list`
     (procfs.c:34), with no cumulative loss counter -> once the queue drains,
     the lost events are untraceable
3. Association state is technically queryable, but nobody queries it:
   - `iwpriv.c:1720` `sta_list`, `:1739` `sta_count` exist
   - but `halow_net_watch.sh` only looks at `flags & 1` (:23) and never queries
     the STA table
4. Recovery actions never touch the STA table:
   - `init.rc:62-69` rebind only does `ip link up` + `addr replace`, L3/L4
     actions that do not rebuild consistency of the driver STA table

Model
-----
State: (n_assoc, n_known, evtq)
  n_assoc in [0,N]  number of STAs truly online
  n_known in [0,N]  number of STAs the AP side (driver / user space) believes in
  evtq    in [0,16] event queue occupancy (HGIC_EVENT_MAX = 16)

Consistency goal: n_known == n_assoc

Action classes
--------------
EXTERNAL (external events, used only to GENERATE reachable states, never counted as recovery)
  sta_join  / sta_leave   camera associates / disassociates, one event each
NORMAL (recovery capability the system itself has)
  evt_drain               user space reads events
  fw_reinit               firmware reinit -> STA table wiped (n_known = 0)
  LHR_reconcile           active query of `sta_count` with reconciliation (LHR variant only)

Why sta_join/leave are excluded from recovery paths: when a camera reconnects is
external behavior, not a recovery mechanism of the system. Counting them as
recovery means pinning one's hopes on the cameras.

Liveness property (session level)
---------------------------------
  From any reachable state, can the system return to n_known == n_assoc using
  its OWN actions alone.

Key provable property: divergence stickiness
  Let d = n_known - n_assoc. Without event loss, sta_join/leave move n_assoc and
  n_known in lockstep, so d is unchanged; with event loss, d drifts one way.
  -> Once d != 0 appears, it does not shrink, except through the uncontrolled
    coincidence of dropping one more event with the opposite sign. This is the
    core mechanism of this model.
"""

from collections import namedtuple, deque

FULL = 16          # HGIC_EVENT_MAX, event.c:26
EXTERNAL, NORMAL = 0, 1


def make_model(N, variant='stock'):
    S = namedtuple('S', 'n_assoc n_known evtq')
    acts = []

    def add(name, kind, g, a, note=''):
        acts.append((name, kind, g, a, note))

    # ---- external events: camera associates / disassociates ----
    # note: n_known is "the number of STAs the AP believes in" and must physically
    # stay in [0, N]. When the queue is full, events are dropped (event.c:68-71)
    # and knowledge does not update -- that is exactly where divergence comes from.
    def _join(s):
        if s.evtq < FULL:
            return S(s.n_assoc + 1, min(N, s.n_known + 1), s.evtq + 1)  # event enqueued, knowledge in sync
        return S(s.n_assoc + 1, s.n_known, s.evtq)                      # event dropped -> knowledge falls behind

    def _leave(s):
        if s.evtq < FULL:
            return S(s.n_assoc - 1, max(0, s.n_known - 1), s.evtq + 1)
        return S(s.n_assoc - 1, s.n_known, s.evtq)

    add('sta_join', EXTERNAL,
        lambda s: s.n_assoc < N, _join,
        'STA associates -> CONNECTED event; when the queue is full event.c:68-71 drops the oldest and AP knowledge does not update')

    add('sta_leave', EXTERNAL,
        lambda s: s.n_assoc > 0, _leave,
        'STA disassociates -> DISCONECTED event; dropped when the queue is full, the AP keeps a stale entry')

    # ---- system actions ----
    add('evt_drain', NORMAL,
        lambda s: s.evtq > 0,
        lambda s: S(s.n_assoc, s.n_known, s.evtq - 1),
        'user-space daemon reads events (does not correct an existing knowledge divergence)')

    add('fw_reinit', NORMAL,
        lambda s: True,
        lambda s: S(s.n_assoc, 0, s.evtq),
        'firmware reinit: STA table wiped -> n_known=0; the STAs are still on the air, divergence becomes -n_assoc')

    if variant == 'lhr':
        add('LHR_reconcile', NORMAL,
            lambda s: True,
            lambda s: S(s.n_assoc, s.n_assoc, s.evtq),
            'LHR-A3: periodically query iwpriv sta_count and reconcile against the true online count, rebuilding consistency')

    return S, acts


def analyse(N, variant='stock'):
    S, acts = make_model(N, variant)
    init = S(N, N, 0)

    # forward BFS (external events allowed) to generate reachable states
    dist = {init: 0}
    parent = {init: None}
    q = deque([init])
    while q:
        s = q.popleft()
        for name, kind, g, a, note in acts:
            if g(s):
                t = a(s)
                if t not in dist:
                    dist[t] = dist[s] + 1
                    parent[t] = (s, name)
                    q.append(t)
    states = set(dist)

    # backward reachability: NORMAL actions only, can we reach a consistent state
    adj = {s: [] for s in states}
    for s in states:
        for name, kind, g, a, note in acts:
            if kind == NORMAL and g(s):
                t = a(s)
                if t in adj:
                    adj[s].append(t)
    rev = {s: [] for s in states}
    for s in states:
        for t in adj[s]:
            rev[t].append(s)

    good, dq = set(), deque()
    for s in states:
        if s.n_known == s.n_assoc:
            good.add(s)
            dq.append(s)
    while dq:
        s = dq.popleft()
        for p in rev[s]:
            if p not in good:
                good.add(p)
                dq.append(p)

    bad = sorted((s for s in states if s not in good),
                 key=lambda s: (dist[s], s.n_assoc, s.n_known))

    # split by cause:
    #   reinit type -- firmware reinit wipes the STA table (n_known=0) while real STAs remain
    #   loss type   -- events dropped at event.c:68-71, knowledge diverges from reality (multi-STA specific)
    bad_reinit = [s for s in bad if s.n_known == 0 and s.n_assoc > 0]
    bad_lost = [s for s in bad if s.n_known != 0 and s.n_known != s.n_assoc]
    bad_lost.sort(key=lambda s: dist[s])

    return dict(N=N, variant=variant, states=states, dist=dist, parent=parent,
                bad=bad, bad_reinit=bad_reinit, bad_lost=bad_lost, init=init)


def path_to(parent, init, t):
    if t == init:
        return []
    out, cur = [], t
    while parent[cur] is not None:
        p, name = parent[cur]
        out.append(name)
        cur = p
        if cur == init:
            break
    out.reverse()
    return out


def burst_loss(N, backlog=0):
    """Number of events lost when all N cameras disassociate at once
    (AP restart / radio outage / mass power cut).

    Queue capacity 16, drop-oldest policy (event.c:68-71).
    Burst of B events + existing backlog -> losses = max(0, B + backlog - 16).
    """
    return max(0, N + backlog - FULL)


def main():
    out = []
    W = out.append
    W("# Multi-STA scenario: session-level liveness report\n")
    W("> Model: `models/multi_sta_model.py`. Deployment: A133 tablet = HaLow AP, N cameras = STAs.\n")
    W("## 1. Scale of liveness violations per N\n")
    W("Counterexamples fall into two causes:\n")
    W("- **Loss type**: events dropped at `event.c:68-71`, so knowledge diverges from reality. "
      "Specific to multi-STA and the core of this model.")
    W("- **Reinit type**: firmware reinit wipes the STA table (`n_known=0`) while the real STAs "
      "are still on the air.\n")
    W("| Cameras N | Reachable states | Liveness violations | Share | Loss type | Reinit type | Shortest loss-type trigger |")
    W("|-----------|------------------|---------------------|-------|-----------|-------------|----------------------------|")
    for N in (2, 4, 8, 12, 16, 20, 24):
        r = analyse(N, 'stock')
        tot, nb = len(r['states']), len(r['bad'])
        bl, br = r['bad_lost'], r['bad_reinit']
        p = path_to(r['parent'], r['init'], bl[0]) if bl else []
        ptxt = " -> ".join(f"`{x}`" for x in p) if p else "(none)"
        W(f"| {N} | {tot} | {nb} | {100.0*nb/tot:.1f}% | {len(bl)} | {len(br)} | {ptxt} |")
    W("")
    W("> The violation share climbs monotonically with N (44% to 92%): more cameras make it "
      "easier for the control plane to enter a state it cannot heal. The curve is itself a "
      "scalability result, and it costs no extra hardware. The model alone yields it.\n")

    W("## 2. Core result under stock\n")
    r = analyse(8, 'stock')
    W(f"At N=8: {len(r['states'])} reachable states, **{len(r['bad'])}** of which violate "
      f"session-level liveness.\n")
    W("Shared trait of the counterexamples: `n_assoc > 0` and `n_known != n_assoc`. The cameras "
      "are online, but what the AP believes diverges from reality.\n")
    W("### Why it cannot return\n")
    W("- `evt_drain` only consumes the queue; it never corrects a knowledge divergence that "
      "already formed (dropped events leave no trace; `procfs.c:34` shows only the current length).")
    W("- `fw_reinit` wipes the STA table (`n_known=0`) while the cameras are still on the air, so "
      "the divergence becomes `n_assoc` and gets larger.")
    W("- The rebind in `init.rc:62-69` only does L3/L4 `ip link up` + `addr replace`. It never "
      "touches the driver STA table.")
    W("- `halow_net_watch.sh:23` only looks at `flags & 1` and never queries `sta_count` "
      "(`iwpriv.c:1739` provides it).")
    W("")
    W("### Smallest counterexample: `sta_leave` -> `fw_reinit` -> `sta_join`\n")
    W("This is the shortest counterexample for every N from 2 to 24, three steps, and every step "
      "happens in practice:\n")
    W("| Step | Action | n_assoc | n_known | What happens |")
    W("|------|--------|---------|---------|--------------|")
    W("| 0 | Initial | N | N | All N cameras online, knowledge matches |")
    W("| 1 | `sta_leave` | N-1 | N-1 | One camera drops, event queued, knowledge still in sync |")
    W("| 2 | `fw_reinit` | N-1 | 0 | Driver triggers firmware reinit, STA table wiped |")
    W("| 3 | `sta_join` | N | 1 | That camera returns, producing a CONNECTED event |")
    W("")
    W("Step 3 is the crux. The other N-1 cameras never left. They still believe they are "
      "associated, so they never re-associate and never produce events. Their records were erased "
      "in step 2. The AP now knows one camera forever, and the other N-1 sessions die silently.\n")
    W("> The recovery mechanism itself creates the worse failure. The reinit the driver performs "
      "to heal itself turns \"one camera dropped\" into \"N-1 cameras permanently gone\". The "
      "amplification factor is N-1.\n")
    W("This counterexample needs no dropped events and no queue overflow. One reinit is enough, "
      "and `detect_work` at `core.c:872-880` triggers reinit whenever the firmware probe fails.\n")

    W("### Divergence stickiness (provable property)\n")
    W("Let `d = n_known - n_assoc`. Without event loss, `sta_join`/`sta_leave` move both sides by "
      "the same step, so d is unchanged. With event loss, d drifts in one direction. Therefore:\n")
    W("> Once d != 0 appears, d does not shrink, except through the uncontrolled coincidence of "
      "dropping one more event with the opposite sign.\n")
    W("Counting on the camera's spontaneous reconnect as a recovery mechanism is wrong. Reconnect "
      "events can be dropped too, and d is sticky under join/leave, so a reconnect does not cancel "
      "an existing divergence.\n")

    W("## 3. Event loss under bursty disassociation (queueing)\n")
    W(f"N cameras disassociating at once (AP restart, radio outage, mass power cut) produce N "
      f"events instantly. Queue capacity is {FULL} (`event.c:26`) and the oldest is dropped "
      f"(`event.c:68-71`):\n")
    W("| N | Lost with empty queue | With 4 backlogged | With 8 backlogged | Consequence |")
    W("|---|----------------------|-------------------|-------------------|-------------|")
    for N in (4, 8, 12, 16, 20, 24):
        a, b, c = burst_loss(N, 0), burst_loss(N, 4), burst_loss(N, 8)
        if N > FULL:
            cons = "Stale entries guaranteed, at least one camera permanently out"
        elif b > 0:
            cons = "No loss at idle, loss with backlog"
        elif c > 0:
            cons = "Loss only with a deep backlog"
        else:
            cons = "No loss"
        W(f"| {N} | {a} | {b} | {c} | {cons} |")
    W("")
    W(f"> The threshold: above N = {FULL}, one network-wide reconnect necessarily drops events. "
      "This is not a probability question but a hard capacity constraint. Every dropped "
      "DISCONNECTED/CONNECTED corresponds to a permanent state divergence for one camera.\n")

    W("## 4. Comparison after the LHR repair\n")
    W("| N | Stock liveness violations | LHR liveness violations |")
    W("|---|---------------------------|-------------------------|")
    for N in (2, 4, 8, 12, 16, 20, 24):
        a = len(analyse(N, 'stock')['bad'])
        b = len(analyse(N, 'lhr')['bad'])
        W(f"| {N} | {a} | {b} |")
    W("")
    W("LHR adds exactly one action: periodically query `iwpriv sta_count` and reconcile against "
      "the true online count (`LHR-A3`). The cost is one iwpriv command and no driver change.\n")

    W("## 5. What this adds to the paper\n")
    W("1. Counterexamples upgrade from \"whole-port outage\" to \"permanent loss of individual "
      "sessions\". Interface-level flags/IP/packet-loss all look normal, N-1 cameras stream fine, "
      "only the k-th is permanently dead. No interface-level watchdog can detect this.")
    W("2. A hard capacity threshold. Above N = 16 a single network-wide reconnect is necessarily "
      "inconsistent. `evt_list=16` turns from an implementation detail into a scalability "
      "constraint, which is the queueing entry point for the real-scalability angle.")
    W("3. The asymmetry of observability is nailed down. STA state is technically queryable "
      "(`sta_list`/`sta_count`), but the existing recovery chain never uses it, and dropped "
      "events leave no counter. The observability claim sharpens from \"not enough information\" "
      "to \"the information exists but is not collected, and the loss is not traceable\".")
    W("4. The repair is cheap. One iwpriv query makes session-level liveness hold, with no driver "
      "change. High impact at low cost is a good selling point.")

    text = "\n".join(out)
    print(text)
    with open('multi_sta_report.md', 'w', encoding='utf-8') as f:
        f.write(text + "\n")


if __name__ == '__main__':
    main()
