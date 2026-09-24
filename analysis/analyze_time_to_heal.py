# -*- coding: utf-8 -*-
"""Extract time-to-heal (LHR success trials) and wipe/rebuild trajectories from board logs.

Usage: python3 analyze_time_to_heal.py [data_dir]
  data_dir defaults to ../data relative to this script.
"""
import glob
import os
import re
import statistics
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data")
E4_DIR = os.path.join(BASE, "20260922_205545_clean", "e4")
EMS_DIR = os.path.join(BASE, "20260922_193407", "raw", "results_20260922_193408")

def stats(name, xs):
    xs = sorted(xs)
    med = statistics.median(xs)
    print(f"{name}: n={len(xs)} values={xs}")
    print(f"{name}: min={min(xs)} p50={med} max={max(xs)}")

# ---- E4 LHR: "SELF_HEAL=1 at Ns" ----
e4 = []
for f in sorted(glob.glob(E4_DIR + "/e4_lhr_*/*.log")):
    txt = open(f, errors="replace").read()
    m = re.search(r"SELF_HEAL=1 at (\d+)s", txt)
    if m:
        e4.append(int(m.group(1)))
stats("E4_LHR_time_to_heal_s", e4)

# ---- EMS LHR: first t=Ns row with mis=0 and alive>=1 after inject ----
ems = []
for f in sorted(glob.glob(EMS_DIR + "/ems_lhr_*.log")):
    txt = open(f, errors="replace").read()
    if "self_heal=1" not in txt:
        continue
    t_heal = None
    for line in txt.splitlines():
        m = re.match(r"t=(\d+)s alive=(\d+) sta_count=(-?\d+) mis=(\d+)", line)
        if m and m.group(4) == "0" and int(m.group(2)) >= 1:
            t_heal = int(m.group(1))
            break
    if t_heal is not None:
        ems.append(t_heal)
stats("EMS_LHR_time_to_heal_s", ems)

# ---- EMS stock failures: wipe/rebuild trajectory signature ----
print("\n--- EMS stock failure trajectories (alive, sta_count) ---")
wipe_sig = 0
fail_n = 0
for f in sorted(glob.glob(EMS_DIR + "/ems_stock_*.log")):
    txt = open(f, errors="replace").read()
    if "self_heal=0" not in txt:
        continue
    fail_n += 1
    base = re.search(r"baseline alive=(\d+) sta_count=(-?\d+)", txt)
    rows = re.findall(r"t=(\d+)s alive=(\d+) sta_count=(-?\d+) mis=\d+", txt)
    traj = [(int(t), int(a), int(s)) for t, a, s in rows]
    b = (int(base.group(1)), int(base.group(2))) if base else ("?", "?")
    # signature: sta_count drops below baseline at inject (wipe/partial wipe),
    # then rebuilds while alive stays 0, ending stale (alive=0, sta_count>0)
    sta_seq = [s for _, _, s in traj]
    end = traj[-1] if traj else None
    dropped = any(s < b[1] for s in sta_seq) if b[1] != "?" else False
    stale_end = end is not None and end[1] == 0 and end[2] > 0
    if dropped and stale_end:
        wipe_sig += 1
    print(f"{os.path.basename(f)}: baseline={b} traj={traj[:4]}...end={end} drop={dropped} stale_end={stale_end}")
print(f"\nfailures={fail_n} with wipe+stale signature={wipe_sig}")
