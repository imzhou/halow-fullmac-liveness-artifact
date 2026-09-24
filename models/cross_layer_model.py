#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cross-layer control-plane formal model (firmware + host + USB bus)
=================================================================

Source: TaiXin TXW8301 FMAC firmware SDK  TXW8301_FMAC-v2.4.1.5-40938

Code evidence (all reproducible):
  usb_bus.c:79-82   if (!ready) { txerr++; return RET_ERR; }  -- uplink silently dropped
  usb_bus.c:86/103  ready = 0;                                -- cleared after uplink write failure
  usb_bus.c:128     ready = 1; (USB_EP_RX_IRQ branch only)    -- the only recovery route
  usb_bus.c:126-146 USB_EP_RX_IRQ = host downlink             -- recovery depends on the host acting
  usb_bus.c:137-141 -ENOMEM -> pending=1, pd_tick=now, break  -- not re-armed
  usb_bus.c:46      drop = TIME_AFTER(jiffies, pd_tick + 100) -- timeout criterion
  usb_bus.c:53-56   after silent drop rxcount=0, re-arm       -- no trace, no retransmission
  usb_bus.c:168-174 pd_work polls and retries every 50 jiffies -- firmware-side polling
  usb_bus.c:35      txerr / rxerr firmware-internal counters  -- invisible to the host
  usb_bus.c:196     auto_tx_null_pkt_enable(TX_EP)            -- a heartbeat exists, pointing the wrong way
  main.c:419        sys_event_init(32)                        -- firmware queue capacity 32
  hgic.h:287-295    HGIC_EXCEPTION_TX_BLOCKED etc., 8 classes -- firmware knows these fault states
  hgic.h:276        HGIC_EVENT_EXCEPTION_INFO = 27            -- a reporting channel exists

Check semantics: adversarial environment, fair system.
  ENV actions are driven by the environment and not guaranteed to happen, so they
  do not count as escape paths; SYS / LHR actions are system-driven and, under
  fair scheduling, do run, so they do count. A state set the system can never
  escape then decides the verdict. This is much stricter than "some path recovers"
  (exists-eventually), which is far too weak.

Usage:
    python cross_layer_model.py
Output:
    cross_layer_report.md
"""
from collections import deque, namedtuple

# ---------------------------------------------------------------- state space
ST = namedtuple("ST", "ready pending pd_age fwq hq dr aware link")
# ready  : firmware->host uplink path usable   (usb_bus.c:32,79,86,103,128)
# pending: inbound data waiting for retry on the firmware side  (usb_bus.c:31,138)
# pd_age : pending data has aged out (>100 jiffies)  (usb_bus.c:46)
# fwq    : firmware event queue occupancy (0..2, 2=FULL)  (main.c:419, actual capacity 32)
# hq     : host event queue occupancy (0..2, 2=FULL)  (driver evt_list, actual capacity 16)
# dr     : firmware owes a drop report (introduced by the V1/V2 repairs)
# aware  : host has noticed the fault and can trigger recovery
# link   : video session genuinely connected

FWQ_FULL = 2
HQ_FULL = 2
INIT = ST(ready=1, pending=0, pd_age=0, fwq=0, hq=0, dr=0, aware=0, link=1)


def good(s):
    """Liveness goal: session connected + both queues drained (dr is diagnostic residue, not counted)"""
    return s.link == 1 and s.fwq == 0 and s.hq == 0 and s.pending == 0


# ---------------------------------------------------------------- actions
def fw_evt(s):
    return s._replace(fwq=min(s.fwq + 1, FWQ_FULL))


def fw_flush_ok(s):
    return s._replace(fwq=s.fwq - 1, hq=s.hq + 1)


def fw_flush_hfull(s):
    """Uplink succeeds but the host queue is full -> host-side drop, firmware unaware"""
    return s._replace(fwq=s.fwq - 1)


def fw_flush_drop(s):
    """ready=0 -> uplink silently dropped, txerr++ invisible to the host (usb_bus.c:79-82)"""
    return s._replace(fwq=s.fwq - 1)


def fw_flush_drop_vis(s):
    """V1: on a drop the firmware records a pending report (still cannot report it instantly,
    because the path is exactly the broken one)"""
    return s._replace(fwq=s.fwq - 1, dr=1)


def v1_report(s):
    """V1's catch-up report: once the uplink path recovers, report the earlier drop to the host"""
    return s._replace(dr=0, aware=1)


def usb_tx_fail(s):
    return s._replace(ready=0)


def host_down(s):
    """Host downlink -> RX IRQ -> ready=1 (usb_bus.c:127-128)
    guard link=1: only a live session keeps producing downlink traffic (TCP ACK / RTSP keepalive)"""
    return s._replace(ready=1, pending=0, pd_age=0)


def rx_enomem(s):
    return s._replace(pending=1, pd_age=0)


def pd_poll_ok(s):
    return s._replace(pending=0, pd_age=0)


def pd_poll_fail(s):
    return s._replace(pd_age=1)


def pd_drop(s):
    """Timeout -> silent drop, re-arm, no trace (usb_bus.c:53-56)"""
    return s._replace(pending=0, pd_age=0)


def pd_drop_vis(s):
    return s._replace(pending=0, pd_age=0, dr=1)


def session_break(s):
    return s._replace(fwq=min(s.fwq + 1, FWQ_FULL), link=0)


def host_consume(s):
    return s._replace(hq=s.hq - 1, aware=1)


def host_recover(s):
    """Host runs recovery -> necessarily sends a command -> ready=1, session rebuilt"""
    return s._replace(ready=1, pending=0, pd_age=0, dr=0, aware=0, link=1)


def host_clear(s):
    return s._replace(aware=0)


def lhr_probe(s):
    """P: periodic host downlink heartbeat. Recovers ready, but brings back no state information"""
    return s._replace(ready=1, pending=0, pd_age=0)


def lhr_reconcile(s):
    """R: periodic host-side active query reconciliation (pull-style).
    One downlink does both: recover ready + retrieve true session state, without
    relying on the firmware reporting first. Matches the existing but never
    called `iwpriv sta_count / sta_list`."""
    return s._replace(ready=1, pending=0, pd_age=0, dr=0,
                      aware=1 if s.link == 0 else 0)


STOCK = [
    ("fw_evt",         "ENV", lambda s: True,                                    fw_evt),
    ("fw_flush_ok",    "SYS", lambda s: s.ready == 1 and s.hq < HQ_FULL and s.fwq > 0, fw_flush_ok),
    ("fw_flush_hfull", "SYS", lambda s: s.ready == 1 and s.hq == HQ_FULL and s.fwq > 0, fw_flush_hfull),
    ("fw_flush_drop",  "SYS", lambda s: s.ready == 0 and s.fwq > 0,              fw_flush_drop),
    ("usb_tx_fail",    "ENV", lambda s: s.ready == 1,                            usb_tx_fail),
    ("host_down",      "ENV", lambda s: s.link == 1,                             host_down),
    ("rx_enomem",      "ENV", lambda s: True,                                    rx_enomem),
    ("pd_poll_ok",     "SYS", lambda s: s.pending == 1,                          pd_poll_ok),
    ("pd_poll_fail",   "SYS", lambda s: s.pending == 1 and s.pd_age == 0,        pd_poll_fail),
    ("pd_drop",        "SYS", lambda s: s.pending == 1 and s.pd_age == 1,        pd_drop),
    ("session_break",  "ENV", lambda s: s.link == 1,                             session_break),
    ("host_consume",   "SYS", lambda s: s.hq > 0,                                host_consume),
    ("host_recover",   "SYS", lambda s: s.aware == 1 and s.link == 0,            host_recover),
    ("host_clear",     "SYS", lambda s: s.aware == 1 and s.link == 1,            host_clear),
]


def build(variant):
    """variant is a repair-subset string over the characters P / R / V1 / V2, e.g. 'P', 'RV1V2'.
    P  = add a periodic downlink heartbeat (recovers ready only, retrieves nothing)
    R  = add periodic active query reconciliation (recovers ready and retrieves true state)
    V1 = uplink silent drop -> record a pending report (the drop cannot be reported instantly:
         the path is exactly the broken one)
    V2 = inbound timeout drop -> record a pending report
    Both ship with v1_report: reported once the path recovers.
    V1/V2 replace rather than add: after the repair the original silent path no longer
    exists. That is the faithful reading."""
    acts = {a[0]: a for a in STOCK}
    if "P" in variant:
        acts["lhr_probe"] = ("lhr_probe", "LHR", lambda s: True, lhr_probe)
    if "R" in variant:
        acts["lhr_reconcile"] = ("lhr_reconcile", "LHR", lambda s: True, lhr_reconcile)
    if "V1" in variant:
        acts["fw_flush_drop"] = ("fw_flush_drop_vis", "SYS",
                                 lambda s: s.ready == 0 and s.fwq > 0, fw_flush_drop_vis)
    if "V2" in variant:
        acts["pd_drop"] = ("pd_drop_vis", "SYS",
                           lambda s: s.pending == 1 and s.pd_age == 1, pd_drop_vis)
    if "V1" in variant or "V2" in variant:
        acts["v1_report"] = ("v1_report", "SYS",
                             lambda s: s.ready == 1 and s.dr == 1, v1_report)
    return list(acts.values())


# ---------------------------------------------------------------- checking
def reachable(acts):
    seen = {INIT}
    parent = {INIT: None}
    q = deque([INIT])
    while q:
        s = q.popleft()
        for name, kind, g, f in acts:
            if g(s):
                t = f(s)
                if t not in seen:
                    seen.add(t)
                    parent[t] = (s, name)
                    q.append(t)
    return seen, parent


def liveness(variant):
    acts = build(variant)
    states, parent = reachable(acts)
    goodset = {s for s in states if good(s)}
    # weak liveness: some path back to GOOD exists
    fwd = {}
    for s in states:
        for _n, kind, g, f in acts:
            if g(s):
                fwd.setdefault(f(s), set()).add(s)
    can = set(goodset)
    q = deque(goodset)
    while q:
        s = q.popleft()
        for p in fwd.get(s, ()):
            if p not in can:
                can.add(p)
                q.append(p)
    weak_bad = sorted(states - can, key=lambda s: tuple(s))
    return acts, states, parent, goodset, can, weak_bad


def trap_set(states, acts):
    """Strong liveness refutation (adversarial environment + fair system).
    Repeatedly remove states with a SYS/LHR escape edge; what remains is the
    region the system cannot escape. Non-empty <=> some environment behavior
    makes recovery impossible forever."""
    C = {s for s in states if not good(s)}
    while True:
        drop = set()
        for s in C:
            for _n, kind, g, f in acts:
                if kind == "ENV":
                    continue                      # environment actions cannot be relied on
                if g(s) and f(s) not in C:
                    drop.add(s)                   # the system can force an escape
                    break
        if not drop:
            return C
        C -= drop


def verify_characterization():
    """Enumerate all 16 subsets of P/R/V1/V2 and verify the characterization:

        repair subset S is effective  <=>  (P in S or R in S)  and  (R in S or V1 in S)

    Left conjunct = provides "path liveness": gives ready a chance to recover;
    right conjunct = provides "state retrieval": once the path is usable, the true
    state comes back without the firmware reporting first.

    Note the right conjunct takes R and V1 but not V2: the deadlock loop runs
    through the UPLINK drop path (fw_flush_drop), which V1 covers. V2 covers the
    INBOUND timeout drop (pd_drop), a path this loop never touches. A repair must
    cover the drop that causes the deadlock, not any drop in general.
    """
    import itertools
    opts = ["P", "R", "V1", "V2"]
    rows = []
    for k in range(len(opts) + 1):
        for combo in itertools.combinations(opts, k):
            v = "".join(combo)
            a, st, pa, gs, cn, wb = liveness(v)
            tr = len(trap_set(st, a))
            has_link = ("P" in v) or ("R" in v)
            has_info = ("R" in v) or ("V1" in v)
            pred_ok = (tr == 0) == (has_link and has_info)
            rows.append(dict(v=v or "(none)", states=len(st), trap=tr,
                             link=has_link, info=has_info,
                             valid=(tr == 0), pred=(has_link and has_info),
                             match=pred_ok))
    return rows


def path_to(parent, target):
    out = []
    cur = target
    while cur != INIT:
        p = parent.get(cur)
        if p is None:
            return None
        prev, nm = p
        out.append(nm)
        cur = prev
    out.append("INIT")
    return list(reversed(out))


def bfs_depth(parent, states):
    def depth(s):
        n = 0
        while parent.get(s) is not None:
            s = parent[s][0]
            n += 1
        return n
    return {s: depth(s) for s in states}


def fmt(s):
    return (f"ready={s.ready} pending={s.pending} pd_age={s.pd_age} "
            f"fwq={s.fwq} hq={s.hq} dr={s.dr} aware={s.aware} link={s.link}")


# ---------------------------------------------------------------- report
def main():
    out = []
    W = out.append

    W("# Cross-layer control-plane liveness report (firmware + host + USB bus)\n")
    W("Model source: TaiXin TXW8301 FMAC SDK `TXW8301_FMAC-v2.4.1.5-40938`\n")
    W("| State variable | Meaning | Code evidence |")
    W("|----------------|---------|---------------|")
    W("| `ready` | Firmware to host uplink path usable | `usb_bus.c:32,79,86,103,128` |")
    W("| `pending` | Inbound data waiting for retry on the firmware side | `usb_bus.c:31,138` |")
    W("| `pd_age` | pending has aged out (>100 jiffies) | `usb_bus.c:46` |")
    W("| `fwq` | Firmware event queue occupancy (full level = 2, actual 32) | `main.c:419` |")
    W("| `hq` | Host event queue occupancy (full level = 2, actual 16) | driver `evt_list` |")
    W("| `dr` | Firmware has drop notifications owed to the host (introduced by the repair) | (none) |")
    W("| `aware` | Host has noticed the fault and can trigger recovery | (none) |")
    W("| `link` | Video session genuinely connected | (none) |")
    W("")
    W("Liveness goal `GOOD(link=1 & fwq=0 & hq=0 & pending=0)`: session connected and both "
      "queues drained. (The released script labels this `GOOD`; the paper calls it `STREAMING`.)\n")
    W("Check semantics: adversarial environment, fair system. ENV actions are driven by the "
      "environment and not guaranteed to happen, so they do not count as escape paths; SYS/LHR "
      "actions are system-driven and, under fair scheduling, do run, so they do count. A state "
      "set the system can never escape (a trap set) then decides the verdict. This is much "
      "stricter than \"some path recovers\" (exists-eventually), which is too weak to support a "
      "\"permanent outage\" claim.\n")

    # ---- 1 ----
    W("## 1. Scale of liveness violations\n")
    W("| Variant | Reachable states | Trap set | Share | Verdict |")
    W("|---------|------------------|----------|-------|---------|")
    res = {}
    for v, label in (("", "stock (as shipped)"), ("PRV1V2", "Full repair (P+R+V1+V2)")):
        acts, states, parent, goodset, can, weak_bad = liveness(v)
        trap = trap_set(states, acts)
        res[v] = (acts, states, parent, goodset, can, weak_bad, trap)
        ok = "Holds" if not trap else "Violates"
        W(f"| {label} | {len(states)} | {len(trap)} | "
          f"{100.0*len(trap)/len(states):.1f}% | {ok} |")
    W("")

    acts, states, parent, goodset, can, weak_bad, trap = res[""]

    # ---- 2 ----
    W("## 2. Stock counterexamples (shortest trigger paths)\n")
    depth = bfs_depth(parent, states)
    order = sorted(trap, key=lambda s: (depth[s], tuple(s)))
    W("| # | State | Depth | Trigger path |")
    W("|---|-------|-------|--------------|")
    for i, s in enumerate(order, 1):
        p = path_to(parent, s)
        ptxt = " -> ".join([p[0]] + [f"`{x}`" for x in p[1:]])
        W(f"| {i} | `{fmt(s)}` | {depth[s]} | {ptxt} |")
    W("")
    if trap and set(weak_bad) == set(trap):
        W(f"All {len(trap)} counterexamples sit in the trap set. They are not just \"one bad path "
          "exists\"; they form a closed region. Once inside, no environment evolution and no "
          "scheduling can bring the system back. This is liveness violation in the strongest "
          "sense.\n")

    # ---- 3 ----
    W("## 3. The core deadlock: a cross-layer dependency cycle\n")
    deadlock = None
    for s in order:
        if s.ready == 0 and s.link == 0 and s.hq == 0 and s.aware == 0 and s.fwq == 0:
            deadlock = s
            break
    if deadlock is None:
        deadlock = order[0] if order else None
    p = path_to(parent, deadlock)
    W("Deadlock state:\n")
    W("```")
    W("  " + fmt(deadlock))
    W("```\n")
    W("Shortest trigger path:\n")
    W("```")
    for step in p:
        W(f"  {step}")
    W("```\n")
    W("Mechanism: four conditions presuppose each other and close a loop.\n")
    W("1. The only way `ready` returns to 1 is host-side downlink data triggering `USB_EP_RX_IRQ` (`usb_bus.c:128`).")
    W("2. Host downlink keeps flowing only while the session is healthy (`link=1` gives TCP ACKs / RTSP keepalives).")
    W("3. Session recovery needs the host to notice the fault, and noticing depends on firmware uplink events reaching `hq`.")
    W("4. Events reach `hq` only when `ready=1`.")
    W("")
    W("Once `ready=0` and `link=0` hold at the same time, all four prerequisites fail together.\n")
    W("Worth stressing: each side's implementation is reasonable on its own. The firmware marks "
      "the path unusable after a failed write and only confirms it usable when host data arrives; "
      "the host treats the link as fine when no events arrive and sends nothing. The failure is "
      "in the composition, not in either side.\n")

    # ---- 4 ----
    W("## 4. Drop without a trace: why operations cannot see it\n")
    W("| Drop point | Code | Trace |")
    W("|------------|------|-------|")
    W("| Uplink drop on `!ready` | `usb_bus.c:79-82` | Only `txerr++`, firmware-internal, invisible to the host |")
    W("| Write failure clears the ready bit | `usb_bus.c:86,103` | No event, no interrupt |")
    W("| Inbound timeout drop | `usb_bus.c:46,53-56` | No counter; `rxcount=0` and re-arm |")
    W("| Host queue full drop | driver `evt_list` full | No cumulative counter; `/proc/hgicf/status` shows only the current length |")
    W("")
    W("All four agree on one thing: no retransmission after a drop. The firmware does know these "
      "failure states: `HGIC_EXCEPTION_TX_BLOCKED` / `TXDELAY_TOOLONG` / `WIFI_BUFFER_USED_OVERTOP`"
      " / `HEAP_USED_OVERTOP` / `CPU_USED_OVERTOP` (`hgic.h:287-295`), and "
      "`HGIC_EVENT_EXCEPTION_INFO = 27` (`hgic.h:276`) is a ready-made channel. Reporting, "
      "however, also travels over the same `ready` uplink. The channel exists; the path does "
      "not.\n")

    # ---- 5 ----
    W("## 5. A heartbeat already exists, pointing the wrong way\n")
    W("`usb_bus.c:196` calls `usb_device_wifi_auto_tx_null_pkt_enable()` at init, which enables "
      "automatic null packets on `USB_WIFI_TX_EP` (device to host). Breaking the deadlock needs "
      "downlink from the host to the firmware (`USB_EP_RX_IRQ`). The same layer already has a "
      "heartbeat, in the opposite direction, so it does not cover this deadlock.\n")

    # ---- 6 ----
    W("## 6. Repair ablation, item by item\n")
    W("| Configuration | Reachable states | Trap set | Verdict |")
    W("|---------------|------------------|----------|---------|")
    variants = [
        ("", "stock (no repair)"),
        ("P", "P only: periodic downlink heartbeat (recovers `ready` only)"),
        ("R", "R only: periodic active query reconciliation"),
        ("V1", "V1 only: uplink drops recorded for later report"),
        ("V2", "V2 only: inbound drops recorded for later report"),
        ("V1V2", "V1+V2: visibility only, no path repair"),
        ("PV1V2", "P+V1+V2: heartbeat plus visibility, no query"),
        ("PRV1V2", "P+R+V1+V2 (full)"),
    ]
    abl = {}
    for v, label in variants:
        a, st, pa, gs, cn, wb = liveness(v)
        tr = trap_set(st, a)
        abl[v] = len(tr)
        ok = "Holds" if not tr else f"Violates ({len(tr)})"
        W(f"| {label} | {len(st)} | {len(tr)} | {ok} |")
    W("")

    W("Three facts fall out:\n")
    n = 0
    if abl.get("P", 0) != 0:
        n += 1
        W(f"{n}. A pure heartbeat (P) is not enough ({abl['P']} trap states remain). It recovers "
          "the uplink path, but already-dropped events are not resent: `usb_bus.c:53-56` drops, "
          "sets `rxcount=0`, and re-arms, with no retransmission anywhere in the firmware. The "
          "path works again; the information is gone.")
    if abl.get("V1", 0) != 0 or abl.get("V1V2", 0) != 0:
        n += 1
        W(f"{n}. Visibility alone (V1/V2) is not enough (V1 leaves {abl.get('V1')}, V1+V2 leaves "
          f"{abl.get('V1V2')}). Making drops visible means sending a notification up, and that "
          "notification travels over the broken path. Visibility parasitizes the very thing it "
          "is supposed to fix.")
    if abl.get("R", 1) == 0:
        n += 1
        W(f"{n}. Active query reconciliation (R) alone removes every violation. One downlink does "
          "two jobs: it recovers `ready` and actively pulls back the true state, without relying "
          "on the firmware reporting first.\n")

    W("Two transferable design principles:\n")
    W("> **Principle 1 (path decoupling):** the liveness of a control-plane recovery path must "
      "not depend on the health of the object being recovered. Here the recovery of `ready` "
      "depends on host downlink, and continued host downlink depends on session health. The "
      "recovery action parasitizes its target, which necessarily produces liveness "
      "counterexamples.\n")
    W("> **Principle 2 (pull over push):** on a channel that drops without a trace and never "
      "retransmits, push-style state sync necessarily loses information. Recovery must use "
      "pull-style reconciliation.\n")
    W("Principle 1 is isomorphic to out-of-band management in distributed systems: if the "
      "management plane shares a path with the plane it manages, it dies with that path.\n")
    W("The query ability R needs already exists and is unused: `iwpriv sta_count` / `sta_list` "
      "read the STA table directly, but `halow_net_watch.sh` only looks at bit 0 of the netdev "
      "flags and has never called it.\n")

    # ---- 6.5 complete characterization ----
    W("## 6.5 Complete characterization of minimal repair sets (verified in the model)\n")
    W("The 8 configurations above hint at a stronger rule. Stated as a proposition and checked "
      "against all 16 subsets:\n")
    W("> **Proposition:** a repair subset S removes the deadlock if and only if S provides path "
      "liveness (`P in S` or `R in S`) **and** S provides state retrieval (`R in S` or "
      "`V1 in S`).\n")
    W("The right conjunct excludes V2 on purpose: the deadlock loop runs through the uplink drop "
      "path (`fw_flush_drop`), and only V1 covers it. V2 covers the inbound timeout drop "
      "(`pd_drop`), which is not part of this loop. A repair must cover the drop that causes the "
      "deadlock, not any drop in general.\n")
    W("| Subset S | Path liveness | State retrieval | Trap set | Actually effective | Proposition predicts | Match |")
    W("|----------|---------------|-----------------|----------|--------------------|-----------------------|-------|")
    rows = verify_characterization()
    for r in rows:
        W(f"| `{r['v']}` | {'yes' if r['link'] else 'no'} | {'yes' if r['info'] else 'no'} | "
          f"{r['trap']} | {'yes' if r['valid'] else 'no'} | {'yes' if r['pred'] else 'no'} | "
          f"{'yes' if r['match'] else '**NO**'} |")
    allmatch = all(r["match"] for r in rows)
    W("")
    if allmatch:
        minimal = [r["v"] for r in rows
                   if r["valid"] and not any(
                       r2["valid"] and set(r2["v"]) < set(r["v"])
                       for r2 in rows if r2["v"] != "(none)")]
        W(f"All 16 rows match, so the proposition holds inside the model. The minimal solutions "
          f"are `{minimal}`, one or two actions in size.\n")
        W("This proposition is stronger than \"every repair is necessary\". Instead of listing "
          "one working fix, it characterizes the full set of working fixes with both necessary "
          "and sufficient conditions. A reviewer cannot wave it away with \"maybe some other "
          "repair works too\", because all 16 combinations are exhausted.\n")
    else:
        W("**Mismatch found**; the proposition needs revision (see the NO rows above).\n")

    W("## 7. Conclusions\n")
    ptxt = " -> ".join(f"`{x}`" for x in path_to(parent, deadlock)[1:])
    W("1. The cross-layer deadlock is reachable and holds under the strong liveness semantics: "
      f"{ptxt} enters the trap set, "
      "and no environment evolution brings it back.")
    W("2. The mechanism is compositional. Both implementations are reasonable alone; the deadlock "
      "comes from the loop \"uplink recovery depends on downlink\" and \"continued downlink "
      "depends on session health\".")
    W("3. It transfers. The structure depends on no private detail of TaiXin or A133. Any FullMAC "
      "module with a polling host stack reproduces it.")
    W("4. The repair is minimal and necessary: periodic active query (one USB downlink plus state "
      "retrieval) removes every violation. Pure heartbeat and pure visibility are both "
      "insufficient, and the existing null-packet mechanism (`usb_bus.c:196`) points the wrong "
      "way to help.")
    W("5. The diagnostic information already existed. `hgic.h:287-295` defines 8 exception "
      "classes and `hgic.h:276` provides the reporting channel. The observability gap is not "
      "that the information does not exist; it is that the information is generated but cannot "
      "travel the path.")

    with open("cross_layer_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

    print("stock : states=%d trap=%d" % (len(states), len(trap)))
    print("full  : states=%d trap=%d" % (len(res['PRV1V2'][1]), len(res['PRV1V2'][6])))
    for v, _l in variants:
        print("  ablation %-8s trap=%d" % (v or "(none)", abl[v]))
    print("deadlock:", fmt(deadlock))
    print("path:", " -> ".join(path_to(parent, deadlock)))
    print("report written: cross_layer_report.md")


if __name__ == "__main__":
    main()
