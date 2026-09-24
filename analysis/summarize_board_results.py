#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Summarize board_results pulled from Windows adb runs."""
from __future__ import print_function
import os
import sys
import glob

ROOT = sys.argv[1] if len(sys.argv) > 1 else "board_results"


def parse_verdict(path):
    d = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
    except OSError:
        return None
    d["_raw"] = text
    for part in text.replace("\n", " ").split():
        if "=" in part:
            k, v = part.split("=", 1)
            d[k] = v
    return d


def main():
    if not os.path.isdir(ROOT):
        print("No directory:", ROOT)
        print("Run experiments on Windows first: scripts/windows/run_board.ps1")
        return 1

    runs = sorted([p for p in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(p)])
    if not runs:
        print("Empty", ROOT)
        return 1

    print("| run | file | self_heal | status | notes |")
    print("|-----|------|-----------|--------|-------|")
    for run in runs:
        name = os.path.basename(run)
        verdicts = glob.glob(os.path.join(run, "*.verdict"))
        verdicts += glob.glob(os.path.join(run, "raw", "**", "*.verdict"), recursive=True)
        seen = set()
        for vp in sorted(verdicts):
            if vp in seen:
                continue
            seen.add(vp)
            d = parse_verdict(vp)
            if not d:
                continue
            sh = d.get("self_heal", "")
            st = d.get("status", "")
            note = d.get("_raw", "")[:80]
            print("| %s | %s | %s | %s | %s |" % (
                name, os.path.basename(vp), sh, st, note.replace("|", "/")))
    print("\nDone. Fill PAPER Table IV from self_heal columns.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
