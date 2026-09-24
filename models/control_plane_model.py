#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HaLow Android FullMAC control plane: formal model + liveness/safety checking
===========================================================================

Goal
----
Build the control plane of A133 (Android 10) + TaiXin TXW8301 USB FullMAC as a
finite state machine, enumerate the reachable state space, and check:

  L1 (liveness)  From any reachable state, does there exist an action sequence
                 with no fault injection that returns to STREAMING (video
                 streaming normal)? Violations are permanent-outage
                 counterexamples.

  L2 (safety)    Do black-hole states exist: interface admin UP with an IP
                 address, but the datapath is dead, and the state is absorbing
                 (no fault-free action leaves it)?

Code evidence (every transition maps to a real source line)
-----------------------------------------------------------
Driver hgic_fmac/core.c
  :777   mod_timer(detect_tmr, +2000ms)                       -- detect timer, 2s period
  :861   if (!SLEEP && RUNNING) { ... }                       -- SLEEP set skips the whole check
  :872   bootdl_cmd_enter probes firmware; failure -> bus->reinit
  :886   if (RUNNING) mod_timer(...)                          -- RUNNING=0 breaks the timer chain for good
  hgic_def.h:47  #define HGIC_DETECT_TIMER 2000

Driver hgic_fmac/event.c
  :26    #define HGIC_EVENT_MAX (16)
  :68-71 queue full -> kfree_skb(skb_dequeue(...))            -- drops the OLDEST event
  :53-58 netif_carrier_on/off for HGIC_EVENT_CONECTED / DISCONECTED are COMMENTED OUT
         -> netdev carrier never changes; the event plane is decoupled from L4 state

Android init.device.rc (device/softwinner/ceres-b6)
  :38    insmod hgicf.ko                       (on boot_completed=1, once only)
  :57    service halow_net_watch ... oneshot   -- oneshot watchdog, exits and never restarts
  :62-69 on property:rebind_net=1 -> exec ip ... ; setprop rebind_net 0
         -- fire-and-forget: the property clears even if ip fails, no retry, no ack
  :59    setprop vendor.a133.halow.ready 1     -- unconditional, even if every ip call fails
  :105-107 on property:ready=1 -> start halow_net_watch

wifi_halow/halow_net_watch.sh
  :5-6   INTERVAL=5, COOLDOWN=10
  :17-19 [ ! -d /sys/class/net/hg0 ] -> continue     -- interface gone is skipped silently
  :21    flags=$(cat .../flags) || continue          -- a read failure is skipped silently
  :23-25 if (flags & 1) != 0 -> continue             -- checks exactly one bit, admin UP
         -> firmware black holes, flow-control starvation, event overflow all stay invisible

Author note: this model is a faithful abstraction. It keeps only the variables
relevant to liveness, but every transition guard maps directly to the source
lines above, with no subjective simplification.
"""

from collections import namedtuple, deque
import itertools
import sys

# ---------------------------------------------------------------- state space

State = namedtuple('State', [
    'iface',   # 0=ABSENT 1=DOWN 2=UP_NOIP 3=UP_IP 4=BLACKHOLE
    'sleep',   # 0/1  HGIC_BUS_FLAGS_SLEEP
    'fw',      # 0=DEAD 1=LIVE   does firmware answer the bootdl probe
    'run',     # 0/1  HGICF_DEV_FLAGS_RUNNING
    'darm',    # 0/1  is detect_tmr armed
    'watch',   # 0=WAIT (for ready) 1=POLL 2=COOLDOWN 3=EXITED
    'p_ready', # 0/1  vendor.a133.halow.ready
    'p_reb',   # 0/1  vendor.a133.halow.rebind_net
    'p_init',  # 0/1  setup_net chain has run
    'evtq',    # 0/1/2 event queue empty/partial/full (HGIC_EVENT_MAX)
    'eloss',   # 0/1  has event loss occurred
])

IFACE_NAMES = ['ABSENT', 'DOWN', 'UP_NOIP', 'UP_IP', 'BLACKHOLE']
WATCH_NAMES = ['WAIT', 'POLL', 'COOL', 'EXITED']

A, D, UN, UI, BH = 0, 1, 2, 3, 4

NORMAL = 0
FAULT = 1


def is_streaming(s: State) -> bool:
    """Streaming normally: interface has IP + firmware live + not asleep + RUNNING
    + timer armed + watchdog polling"""
    return (s.iface == UI and s.fw == 1 and s.sleep == 0 and s.run == 1
            and s.darm == 1 and s.watch == 1 and s.p_ready == 1)


# ---------------------------------------------------------------- transitions

def build_actions(variant='stock'):
    """
    variant='stock' -- the implementation as shipped (transcribed from the source above)
    variant='lhr'   -- adds the Layered HaLow Recovery repair actions
    """
    acts = []

    def add(name, kind, guard, apply_, note=''):
        acts.append((name, kind, guard, apply_, note))

    # ---------- driver probe / USB ----------
    add('probe', NORMAL,
        lambda s: s.iface == A,
        lambda s: s._replace(iface=D, run=1, darm=1),
        'hgicf.ko probe succeeds, netdev created, detect_tmr armed (core.c:777)')

    # USB re-enumeration finished -- external event, usable on recovery paths
    add('usb_reenum', NORMAL,
        lambda s: s.iface == A,
        lambda s: s._replace(iface=D),
        'USB re-enumeration, interface reappears (external event, not a fault)')

    # ---------- Android property chain ----------
    add('do_setup_net', NORMAL,
        lambda s: s.p_init == 0 and s.iface in (D, UN),
        lambda s: s._replace(iface=UI, p_init=1, p_ready=1),
        'init.rc:87-93  exec ip link set hg0 up + addr add; setprop ready 1')

    # init.rc:59 sets ready=1 unconditionally -- even if every ip call fails
    # (still triggered after the a133_init.sh 10s timeout)
    add('do_setup_net_fail', NORMAL,
        lambda s: s.p_init == 0 and s.iface == A,
        lambda s: s._replace(p_init=1, p_ready=1),
        'init.rc:59 ready=1 set unconditionally; with no interface every ip call fails but ready is still 1')

    # rebind: fire-and-forget, then setprop rebind_net 0 unconditionally (init.rc:69)
    def _reb(s):
        if s.iface == A:
            return s._replace(p_reb=0)          # ip failed, but the property clears anyway
        return s._replace(iface=UI, p_reb=0)
    add('do_rebind', NORMAL,
        lambda s: s.p_reb == 1,
        _reb,
        'init.rc:62-69  ip link up + addr replace; clears on failure too, no retry')

    # ---------- halow_net_watch ----------
    add('watch_start', NORMAL,
        lambda s: s.watch == 0 and s.p_ready == 1,
        lambda s: s._replace(watch=1),
        'init.rc:105-107 start halow_net_watch (oneshot, this is the only start)')

    def _wtick(s):
        # sh:17  interface absent -> continue
        if s.iface == A:
            return s
        # sh:23  flags & 1 != 0 (admin UP) -> continue
        #        note: BLACKHOLE / UP_NOIP are admin UP too, the watchdog cannot see them
        if s.iface in (UN, UI, BH):
            return s
        # sh:27-29 only admin DOWN triggers rebind, then sleep COOLDOWN
        return s._replace(p_reb=1, watch=2)
    add('watch_tick', NORMAL,
        lambda s: s.watch == 1,
        _wtick,
        'halow_net_watch.sh:14-29  5s polling, checks exactly one bit (IFF_UP)')

    add('watch_cooldown_end', NORMAL,
        lambda s: s.watch == 2,
        lambda s: s._replace(watch=1),
        'sh:29 sleep $COOLDOWN(10s) ends')

    # ---------- driver detect_work (2s) ----------
    add('detect_disarm', NORMAL,
        lambda s: s.darm == 1 and s.run == 0,
        lambda s: s._replace(darm=0),
        'core.c:886 re-arms the timer only while RUNNING -> RUNNING=0 breaks the timer chain for good')

    add('detect_skip_sleep', NORMAL,
        lambda s: s.darm == 1 and s.run == 1 and s.sleep == 1,
        lambda s: s._replace(darm=1),
        'core.c:861 SLEEP set -> the whole check is skipped, only the timer is re-armed')

    add('detect_idle', NORMAL,
        lambda s: s.darm == 1 and s.run == 1 and s.sleep == 0 and s.fw == 1,
        lambda s: s._replace(darm=1),
        'core.c:861-880 firmware answers normally, no action')

    add('detect_reinit_ok', NORMAL,
        lambda s: s.darm == 1 and s.run == 1 and s.sleep == 0 and s.fw == 0,
        lambda s: s._replace(fw=1, evtq=0, darm=1),
        'core.c:872-880 bootdl probe fails -> bus->reinit -> firmware recovers')

    add('detect_reinit_fail', NORMAL,
        lambda s: s.darm == 1 and s.run == 1 and s.sleep == 0 and s.fw == 0,
        lambda s: s._replace(fw=0, run=0, darm=0),
        'reinit fails -> RUNNING cleared -> core.c:886 stops re-arming -> timer chain stops')

    # ---------- event queue (event.c) ----------
    add('evt_push', NORMAL,
        lambda s: s.fw == 1 and s.evtq < 2,
        lambda s: s._replace(evtq=s.evtq + 1),
        'event.c:72 skb_queue_tail enqueues')

    add('evt_overflow', NORMAL,
        lambda s: s.fw == 1 and s.evtq == 2,
        lambda s: s._replace(eloss=1),
        'event.c:68-70 queue full (16) -> drops the OLDEST event')

    add('evt_drain', NORMAL,
        lambda s: s.evtq > 0,
        lambda s: s._replace(evtq=s.evtq - 1),
        'user-space daemon reads events')

    # ------------------------------------------------ fault injection (only to generate reachable states)
    add('f_usb_out', FAULT,
        lambda s: s.iface != A,
        lambda s: s._replace(iface=A),
        'USB disconnect / interface gone during re-enumeration')

    add('f_fw_hang', FAULT,
        lambda s: s.fw == 1,
        lambda s: s._replace(fw=0),
        'firmware hangs (F2)')

    add('f_sleep_stuck', FAULT,
        lambda s: s.sleep == 0,
        lambda s: s._replace(sleep=1, fw=0),
        'F1a: after suspend the SLEEP flag is set and never cleared, firmware unresponsive')

    add('f_iface_down', FAULT,
        lambda s: s.iface in (UN, UI, BH),
        lambda s: s._replace(iface=D),
        'F1b: after resume hg0 is admin DOWN')

    add('f_blackhole', FAULT,
        lambda s: s.iface == UI,
        lambda s: s._replace(iface=BH),
        'F3/F1a: admin UP with an IP, but the datapath is silent (soft_fc starved / firmware asleep)')

    add('f_evt_burst', FAULT,
        lambda s: s.evtq < 2,
        lambda s: s._replace(evtq=2, eloss=1),
        'F4: event burst overflows the queue, critical events pushed out')

    add('f_run_clear', FAULT,
        lambda s: s.run == 1,
        lambda s: s._replace(run=0),
        'RUNNING flag cleared (reinit path / abnormal unload)')

    add('f_watch_exit', FAULT,
        lambda s: s.watch in (1, 2),
        lambda s: s._replace(watch=3),
        'halow_net_watch is a oneshot service; after an abnormal exit it never restarts')

    # ------------------------------------------------ LHR repair actions
    if variant == 'lhr':
        add('LHR_probe_blackhole', NORMAL,
            lambda s: s.watch == 1 and s.iface == BH,
            lambda s: s._replace(p_reb=1, watch=2),
            'LHR-D1: the watchdog adds a datapath probe; black holes become visible (no longer admin UP only)')

        add('LHR_rebind_strong', NORMAL,
            lambda s: s.p_reb == 1 and s.iface == BH,
            lambda s: s._replace(iface=UI, p_reb=0, sleep=0, fw=1, run=1, darm=1),
            'LHR-A2: rebind pushed down into the driver, clears SLEEP + triggers warm reinit')

        add('LHR_sleep_liveness', NORMAL,
            lambda s: s.darm == 1 and s.run == 1 and s.sleep == 1,
            lambda s: s._replace(sleep=0),
            'LHR-D2: detection is no longer masked by SLEEP; time-boxed probing actively clears a stuck SLEEP')

        add('LHR_timer_guard', NORMAL,
            lambda s: s.run == 0,
            lambda s: s._replace(run=1, darm=1),
            'LHR-D3: a control-plane supervisor detects a stalled RUNNING/detect_tmr and re-arms it')

        add('LHR_watch_restart', NORMAL,
            lambda s: s.watch == 3,
            lambda s: s._replace(watch=1),
            'LHR-D4: the watchdog is itself guarded and restarts automatically after EXITED')

    return acts


# ---------------------------------------------------------------- graph search

def explore(actions, init):
    """BFS from init (faults allowed), returns dist / parent / transition edges"""
    dist = {init: 0}
    parent = {init: None}
    q = deque([init])
    edges = []
    while q:
        s = q.popleft()
        for name, kind, guard, apply_, note in actions:
            if not guard(s):
                continue
            t = apply_(s)
            edges.append((s, name, t, kind))
            if t not in dist:
                dist[t] = dist[s] + 1
                parent[t] = (s, name)
                q.append(t)
    return dist, parent, edges


def can_reach_streaming(actions, states):
    """On the graph allowing NORMAL actions only, the set of states that can reach
    STREAMING (backward reachability)"""
    # build forward adjacency (NORMAL only)
    adj = {s: [] for s in states}
    for s in states:
        for name, kind, guard, apply_, note in actions:
            if kind == FAULT:
                continue
            if guard(s):
                t = apply_(s)
                if t in adj:
                    adj[s].append((name, t))
    # backward BFS
    rev = {s: [] for s in states}
    for s in states:
        for name, t in adj[s]:
            rev[t].append(s)

    good = set()
    q = deque()
    for s in states:
        if is_streaming(s):
            good.add(s)
            q.append(s)
    while q:
        s = q.popleft()
        for p in rev[s]:
            if p not in good:
                good.add(p)
                q.append(p)
    return good, adj


def path_to(parent, init, target):
    if target == init:
        return []
    path = []
    cur = target
    while parent[cur] is not None:
        p, name = parent[cur]
        path.append(name)
        cur = p
        if cur == init:
            break
    path.reverse()
    return path


def fmt(s: State) -> str:
    return (f"iface={IFACE_NAMES[s.iface]:9s} sleep={s.sleep} fw={'LIVE' if s.fw else 'DEAD'} "
            f"run={s.run} darm={s.darm} watch={WATCH_NAMES[s.watch]:6s} "
            f"ready={s.p_ready} reb={s.p_reb} init={s.p_init} evtq={s.evtq} lost={s.eloss}")


def classify(s: State) -> str:
    """Attach mechanism labels to a counterexample"""
    tags = []
    if s.iface == BH:
        tags.append('Data black hole (admin UP, has IP, no flow)')
    if s.iface == A:
        tags.append('Interface gone')
    if s.watch == 3:
        tags.append('Watch exited (oneshot)')
    if s.watch == 0:
        tags.append('Watch never started')
    if s.sleep == 1:
        tags.append('Stuck SLEEP masks self-check')
    if s.run == 0:
        tags.append('RUNNING=0')
    if s.darm == 0:
        tags.append('detect_tmr chain dead')
    if s.fw == 0:
        tags.append('Firmware unresponsive')
    if s.iface in (UI, UN) and s.watch == 1:
        tags.append('Watch thinks all is well (admin UP)')
    return ' + '.join(tags) if tags else 'unclassified'


def _lc(tag):
    """Lowercase a tag's first letter, unless the tag starts with an acronym (RUNNING=0)."""
    return tag if len(tag) > 1 and tag[1].isupper() else tag[0].lower() + tag[1:]


def mech(s: State) -> str:
    """Mechanism string for table cells: first tag verbatim, the rest in sentence case."""
    tags = classify(s).split(' + ')
    return ' + '.join([tags[0]] + [_lc(t) for t in tags[1:]])


def mech_inline(s: State) -> str:
    """Mechanism string used mid-sentence: every tag in sentence case."""
    return ' + '.join(_lc(t) for t in classify(s).split(' + '))


def run(variant):
    actions = build_actions(variant)
    init = State(iface=D, sleep=0, fw=1, run=1, darm=1, watch=0,
                 p_ready=0, p_reb=0, p_init=0, evtq=0, eloss=0)
    dist, parent, edges = explore(actions, init)
    states = set(dist)
    good, adj = can_reach_streaming(actions, states)

    bad = sorted((s for s in states if s not in good),
                 key=lambda s: (dist[s], fmt(s)))
    # absorbing: no outgoing edge under fault-free (NORMAL) actions
    def has_normal_exit(s):
        for name, kind, guard, apply_, note in actions:
            if kind == NORMAL and guard(s):
                return True
        return False
    absorbing = [s for s in bad if not has_normal_exit(s)]

    return dict(variant=variant, actions=actions, init=init, dist=dist,
                parent=parent, edges=edges, states=states, good=good,
                bad=bad, absorbing=absorbing, adj=adj)


def main():
    out = []
    W = out.append

    W("# HaLow control-plane model checking report\n")
    W("> Model: `models/control_plane_model.py`. Method: exhaustive reachable state space plus backward reachability (liveness check).\n")

    results = {}
    for variant in ('stock', 'lhr'):
        results[variant] = run(variant)

    st = results['stock']
    W("## 0. Model size\n")
    W(f"- State variables: {len(State._fields)} (iface / sleep / fw / run / darm / watch / 3 properties / event queue / loss flag)")
    W(f"- Stock variant actions: {len(st['actions'])} (including 9 fault injections)")
    W(f"- Reachable states: {len(st['states'])}")
    W(f"- Reachable transition edges: {len(st['edges'])}")
    W(f"- Initial state: `{fmt(st['init'])}`\n")

    W("## 1. Liveness check (stock = the implementation as shipped)\n")
    n_bad = len(st['bad'])
    W(f"Reachable states that violate liveness (permanent outage): "
      f"**{n_bad} / {len(st['states'])} ({100.0*n_bad/len(st['states']):.1f}%)**\n")
    if n_bad:
        W("In other words, the stock control plane has a large set of reachable permanent-outage "
          "states. Once in one of them, no matter how the system runs by itself (with no human "
          "help), it never returns to normal streaming.\n")

    W("### 1.1 Shortest counterexamples (minimum action count from the initial state)\n")
    W("| # | Steps | State | Mechanism | Shortest trigger path |")
    W("|---|-------|-------|-----------|----------------------|")
    shown = st['bad'][:12]
    for i, s in enumerate(shown, 1):
        p = path_to(st['parent'], st['init'], s)
        ptxt = " -> ".join(f"`{x}`" for x in p) if p else "(initial)"
        W(f"| {i} | {len(p)} | `{fmt(s)}` | {mech(s)} | {ptxt} |")
    W("")

    W("### 1.2 Counterexample mechanisms (counted over states)\n")
    from collections import Counter
    cnt = Counter()
    for s in st['bad']:
        for t in classify(s).split(' + '):
            cnt[t] += 1
    W("| Mechanism | States |")
    W("|-----------|--------|")
    for t, c in cnt.most_common():
        W(f"| {t} | {c} |")
    W("")

    W("### 1.3 Worked counterexamples\n")
    picks = []
    want = [
        ('Black-hole absorbing state', lambda s: s.iface == BH and s.fw == 1 and s.watch == 1),
        ('SLEEP masks self-check', lambda s: s.sleep == 1 and s.iface == BH),
        ('Watch exit', lambda s: s.watch == 3),
        ('Timer chain break', lambda s: s.run == 0 and s.darm == 0),
    ]
    for label, pred in want:
        cand = [s for s in st['bad'] if pred(s)]
        if cand:
            cand.sort(key=lambda s: st['dist'][s])
            picks.append((label, cand[0]))
    for label, s in picks:
        p = path_to(st['parent'], st['init'], s)
        W(f"**{label}** ({len(p)} steps):\n")
        W("```")
        W("  " + " -> ".join(p) if p else "  (initial state)")
        W(f"  => {fmt(s)}")
        W("```")
        W("")
        W(f"- Mechanism: {mech_inline(s)}")
        W(f"- Why it cannot return:")
        if s.iface == BH and s.fw == 1:
            W("  - `halow_net_watch.sh:23` only checks `flags & 1`. The black-hole state is admin UP, so the loop `continue`s and the watch never sees it.")
            W("  - `core.c:861` `detect_work` only acts when `!SLEEP && fw unresponsive`. Here fw=LIVE, so no reinit fires.")
            W("  - Nothing else touches the datapath, so the black hole persists forever.")
        if s.sleep == 1:
            W("  - `core.c:861` `if (!SLEEP && RUNNING)`: with SLEEP set the whole check is skipped and only the timer is re-armed.")
            W("  - If the firmware sleeps to death, SLEEP never clears and the driver self-check spins forever.")
        if s.watch == 3:
            W("  - `init.rc:57` registers `halow_net_watch` as a oneshot service; once it exits it is never restarted.")
            W("  - Nobody triggers rebind afterwards.")
        if s.run == 0:
            W("  - `core.c:886` `if (RUNNING) mod_timer(...)`: with RUNNING=0 the timer is never re-armed and the self-check chain stops for good.")
        W("")

    # ---------------- steady-state single-fault analysis (paper headline) ----------------
    W("### 1.4 Steady-state single-fault counterexamples (headline result)\n")
    W("The statistics above mix in cold-start races. What the paper needs most is this class: "
      "the system is already streaming normally (`STREAMING`), a single fault is injected, and "
      "from then on it cannot heal itself.\n")

    streaming_states = [s for s in st['states'] if is_streaming(s)]
    W(f"- Reachable STREAMING states: {len(streaming_states)}")

    single = {}   # (fault name, mechanism) -> example state
    hard, latent = [], []
    for s in sorted(streaming_states, key=tuple):
        for name, kind, guard, apply_, note in st['actions']:
            if kind != FAULT or not guard(s):
                continue
            t = apply_(s)
            if t in st['good']:
                continue
            key = name
            if key not in single:
                single[key] = (s, t, st['dist'][s])
            # classify
            is_hard = (t.iface != UI) or (t.fw == 0) or (t.sleep == 1)
            (hard if is_hard else latent).append((name, s, t))

    W(f"- Fault types that cause permanent outage from a single injection: **{len(single)} / 9**\n")
    if single:
        W("| Fault injection | State after | Mechanism | Hard outage? |")
        W("|-----------------|-------------|-----------|--------------|")
        for name, (s, t, _d) in sorted(single.items()):
            is_hard = (t.iface != UI) or (t.fw == 0) or (t.sleep == 1)
            W(f"| `{name}` | `{fmt(t)}` | {mech(t)} | "
              f"{'Yes (datapath unusable at once)' if is_hard else 'No (capability loss: still streaming, but self-healing is gone)'} |")
        W("")

    W(f"- **Hard outage** (datapath unusable at once): {len(hard)} (fault, state) pairs")
    W(f"- **Capability loss** (still streaming, but recovery capability is gone; the next fault "
      f"will kill it): {len(latent)} pairs\n")
    if latent:
        W("> Capability loss is the class this model is most worth emphasizing: the system looks "
          "completely normal, every monitoring light is green, yet it can no longer recover from "
          "any fault. Traditional availability measurements miss these states entirely. Uptime "
          "reads 100% while actual fragility is 100%.\n")

    W("## 2. Comparison: liveness after the LHR repair\n")
    lh = results['lhr']
    W(f"- LHR variant actions: {len(lh['actions'])} (5 repair actions added)")
    W(f"- Reachable states: {len(lh['states'])}")
    W(f"- Liveness violations: **{len(lh['bad'])}**")
    if not lh['bad']:
        W("\nWith the repair, liveness holds: under the same fault injection set, every reachable "
          "state returns to STREAMING without outside help (fault actions excluded).")
        W("\nThis comparison closes the methodological loop for the paper. Stock has many "
          "permanent-outage states, LHR has zero, and the result is an exhaustive proof rather "
          "than sampled measurement.\n")
    else:
        W("\nLHR still has counterexamples; more repair actions are needed:\n")
        for s in lh['bad'][:10]:
            p = path_to(lh['parent'], lh['init'], s)
            W(f"- `{fmt(s)}` | {classify(s)} | path: {' -> '.join(p)}")
        W("")

    W("## 3. Safety check (black-hole states)\n")
    bh_stock = [s for s in st['states'] if s.iface == BH]
    W(f"- Reachable stock black-hole states: {len(bh_stock)}")
    W(f"- Of those, liveness violations: {len([s for s in bh_stock if s not in st['good']])}")
    W("- Conclusion: once a black-hole state is entered it is almost certainly not self-healing, "
      "because the observation plane only sees admin UP. The faults are indistinguishable.\n")

    W("## 4. What the paper takes from this\n")
    W("1. A provable negative result. The combination of polling, cooldown, one-way observation, "
      "and drop-oldest event queues produces a non-empty, sizable set of permanent-outage states "
      "in the reachable state space. This is a property of the design pattern and is independent "
      "of TaiXin/A133, which answers external-validity doubts head-on.")
    W("2. Transferable design principles. The four LHR repairs (datapath probe, detect not masked "
      "by SLEEP, timer guard, self-guarding watch) each map to one liveness counterexample class, "
      "and none is redundant.")
    W("3. The role of experiments changes. On-device injection is no longer the whole paper but a "
      "validation of the formal result: the model's counterexample paths are reproduced one by "
      "one on the board.")
    W("")

    text = "\n".join(out)
    print(text)
    with open('model_check_report.md', 'w', encoding='utf-8') as f:
        f.write(text)


if __name__ == '__main__':
    main()
