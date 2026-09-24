# Experiment plan

## 0. Prerequisites

- [ ] Cameras online and associated over hg0 (`hgpriv hg0 get sta_list` or dnsmasq leases)
- [ ] Tablet pings 172.16.0.x
- [ ] Repeatable logging on: periodic `/proc/hgicf/status` sampling plus dmesg
- [ ] Without a real video stream: `iperf3 -u -b 300k` on the peer or locally to simulate uplink/downlink

## 1. Metric definitions

| Metric | Definition |
|--------|------------|
| Outage | Duration over which application goodput stays at 0 (or a continuous window of ping loss) |
| MTTR | Fault injection done until goodput recovers to 80% of its pre-fault value |
| Recovery rate | Recoveries within 120 s over 30 injections, divided by 30 |
| False recovery | Times LHR wrongly triggers reinit/rebind with no fault present |
| Reinit count | Times detect triggers `bus->reinit` |
| Session survival | Whether the streaming session survives without a user restart (1/0) |

Sampling at 1 s granularity. Timestamp key paths in kmsg.

## 2. Injection matrix (P0 first)

| ID | Fault | Injection | Expected observation |
|----|-------|-----------|----------------------|
| P0-1 | hg0 down after resume | `echo mem > /sys/power/state`, or screen-off sleep then wake | flags bit0=0; watch rebind |
| P0-2 | Simulated firmware hang | Unreliable: try stopping responses without unplugging USB, or brief `ifconfig hg0 down/up` plus filling `soft_fc` | `detect_tmr` to reinit |
| P0-3 | USB re-enumeration | unbind/bind the USB device node if permitted | reinit and netdev rebuild |
| P0-4 | Strong interference / adjacent channel | Co-channel device or frequency sweep | TXDELAY / throughput collapse |
| P1 | STA power cycle | Cut camera power for 5 to 30 s | DISCONNECT event, then re-association |
| P1 | Property chain stuck | Stop `halow_net_watch` manually | Compare with and without watch |
| P2 | Event storm | Frequent connect/disconnect | `evt_list` overflow |

## 3. Baselines

| Code | Configuration |
|------|---------------|
| B0 | Stock as shipped (watch + rebind) |
| B1 | Naive only: manual `ip link set up` + `addr replace` after injection, no event coordination |
| LHR | The mechanism of this paper (swap in once implemented) |

## 4. Protocol per run

1. Warm up 60 s and record baseline goodput G0.
2. Inject the fault and record t0.
3. Monitor until recovery or the 120 s timeout, record t1.
4. Cool down 30 s, repeat N=30 (N=10 is acceptable to start).
5. Export outage = t1 - t0 and whether the session survived.

## 5. Table templates

### T1: fault x mechanism

| Fault | Metric | B0 | B1 | LHR |
|-------|--------|----|----|-----|
| P0-1 | MTTR mean/p95 | | | |
| P0-1 | Outage mean | | | |
| P0-1 | Recv rate % | | | |
| ... | ... | | | |

### T2: overhead

| Scheme | CPU% | Extra packets/s | False recovery / 10 min |
|--------|------|-----------------|-------------------------|
| B0 | | | |
| LHR | | | |

## 6. Smallest publishable set (when short on time)

Run only P0-1 + P0-3 + one traffic type with N=20, and produce a CDF plus table T1.
Add P0-2 or the STA power cycle later to strengthen the story.

## 7. Board command cheatsheet

```sh
# state
cat /proc/hgicf/status
hgpriv hg0 get signal
hgpriv hg0 get conn_state
# link
ip link show hg0
ping -c 5 172.16.0.x
# logs
dmesg | tail
logcat -b all | grep -iE 'halow|hg0|hgic'
```
