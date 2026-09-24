#!/system/bin/sh
# Default suite: E4 stock + E4 LHR + EMS stock + EMS LHR. E2 off.
# Pass >=2 peer IPs for Claim-2 multi-STA board check.
#   sh run_suite.sh /data/local/tmp/halow_exp 172.16.0.100 172.16.0.101

BASE=${1:-/data/local/tmp/halow_exp}
shift
PEERS=${*:-172.16.0.100}
N=${N_REPEAT:-5}
E4_TO=${E4_TO:-25}
EMS_TO=${EMS_TO:-40}
E2_TO=${E2_TO:-25}
RUN_E2=${RUN_E2:-0}
OUT=$BASE/results_$(date +%Y%m%d_%H%M%S)
mkdir -p "$OUT"
export OUTDIR="$OUT"
export TIMEOUT="$EMS_TO"
export INTERVAL=3
export PATH="$BASE:$PATH"

npeers=0
for _ in $PEERS; do npeers=$((npeers+1)); done

echo "suite out=$OUT peers=$PEERS npeers=$npeers N=$N RUN_E2=$RUN_E2"
echo "suite out=$OUT peers=$PEERS npeers=$npeers N=$N RUN_E2=$RUN_E2" >> "$OUT/suite.log"
if [ "$npeers" -lt 2 ]; then
  echo "WARN: npeers=$npeers (<2). EMS validates link-bounce mismatch only; Claim-2 N-1 amp needs >=2 cameras." | tee -a "$OUT/suite.log"
fi

restore_soft() {
  echo "[restore_soft]"
  hgpriv hg0 set sleep=0,0 2>/dev/null || true
  ip link set hg0 up 2>/dev/null || ifconfig hg0 up 2>/dev/null || true
  ip addr replace 172.16.0.1/24 dev hg0 2>/dev/null || true
  ip route replace 172.16.0.0/24 dev hg0 table 100 2>/dev/null || true
  setprop vendor.a133.halow.rebind_net 1 2>/dev/null || true
  setprop ctl.start halow_net_watch 2>/dev/null || true
}

i=1
while [ "$i" -le "$N" ]; do
  echo ""
  echo "==== round $i/$N E4 stock ===="
  echo "==== round $i/$N E4 stock ====" >> "$OUT/suite.log"
  sh "$BASE/run_e4_watchdog.sh" "$E4_TO" "$OUT/e4_stock_$i" stock || true
  restore_soft
  sleep 2

  echo "==== round $i/$N E4 lhr ===="
  echo "==== round $i/$N E4 lhr ====" >> "$OUT/suite.log"
  sh "$BASE/run_e4_watchdog.sh" "$E4_TO" "$OUT/e4_lhr_$i" lhr || true
  restore_soft
  sleep 2

  echo "==== round $i/$N EMS stock ===="
  echo "==== round $i/$N EMS stock ====" >> "$OUT/suite.log"
  sh "$BASE/run_multista_reconcile.sh" stock $PEERS || true
  sleep 2

  echo "==== round $i/$N EMS lhr ===="
  echo "==== round $i/$N EMS lhr ====" >> "$OUT/suite.log"
  sh "$BASE/run_multista_reconcile.sh" lhr $PEERS || true
  sleep 2

  if [ "$RUN_E2" = "1" ]; then
    echo "==== round $i/$N E2 (DANGER) ===="
    sh "$BASE/run_e2_sleep.sh" 1 5000 "$E2_TO" || true
    hgpriv hg0 set sleep=0,0 2>/dev/null || true
    restore_soft
    sleep 2
  else
    echo "==== round $i/$N E2 SKIPPED ===="
  fi

  i=$((i+1))
done

echo "==== summarize verdicts ===="
for f in "$OUT"/*.verdict "$OUT"/*/*.verdict; do
  [ -f "$f" ] || continue
  echo "$f"
  cat "$f"
done
echo "DONE $OUT"
restore_soft
