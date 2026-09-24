#!/system/bin/sh
# Measure LHR pull overhead: hgpriv get sta_count latency + coarse CPU.
# Usage:
#   measure_lhr_overhead.sh [N_samples] [outdir]
# Env: IF=hg0 HGPRIV=hgpriv

N=${1:-100}
OUT=${2:-/data/local/tmp/halow_exp/overhead}
IF=${IF:-hg0}
HGPRIV=${HGPRIV:-hgpriv}
mkdir -p "$OUT"
TS=$(date +%Y%m%d_%H%M%S)
CSV="$OUT/overhead_$TS.csv"
SUM="$OUT/overhead_$TS.summary"
LOG="$OUT/overhead_$TS.log"

log() { echo "[OH] $*"; echo "$*" >> "$LOG"; }

echo "i,t_ms,ok" > "$CSV"
log "=== overhead N=$N IF=$IF ==="

# Warm-up
$HGPRIV "$IF" get sta_count >/dev/null 2>&1 || true

i=1
ok_n=0
# accumulate ms in integer tenths if possible
while [ "$i" -le "$N" ]; do
  # Android toybox date may lack %N; fall back to seconds+busybox
  if date +%s%N >/dev/null 2>&1; then
    t0=$(date +%s%N)
    out=$($HGPRIV "$IF" get sta_count 2>/dev/null || echo FAIL)
    t1=$(date +%s%N)
    # ns -> ms
    dt=$(( (t1 - t0) / 1000000 ))
  else
    # 1ms resolution via /proc/uptime if present
    t0=$(cat /proc/uptime 2>/dev/null | awk '{printf "%d", $1*1000}')
    out=$($HGPRIV "$IF" get sta_count 2>/dev/null || echo FAIL)
    t1=$(cat /proc/uptime 2>/dev/null | awk '{printf "%d", $1*1000}')
    dt=$((t1 - t0))
  fi
  ok=1
  echo "$out" | grep -qi FAIL && ok=0
  [ "$ok" -eq 1 ] && ok_n=$((ok_n + 1))
  echo "$i,$dt,$ok" >> "$CSV"
  i=$((i + 1))
done

# Sort latencies for percentiles (awk)
awk -F, 'NR>1 && $3==1 {print $2}' "$CSV" | sort -n > "$OUT/lat_sorted_$TS.txt"
nlines=$(wc -l < "$OUT/lat_sorted_$TS.txt" | tr -d ' ')
p50=p95=p99=max=min=0
if [ "$nlines" -gt 0 ]; then
  min=$(sed -n '1p' "$OUT/lat_sorted_$TS.txt")
  max=$(tail -1 "$OUT/lat_sorted_$TS.txt")
  i50=$(( (nlines * 50 + 99) / 100 )); [ "$i50" -lt 1 ] && i50=1
  i95=$(( (nlines * 95 + 99) / 100 )); [ "$i95" -lt 1 ] && i95=1
  i99=$(( (nlines * 99 + 99) / 100 )); [ "$i99" -lt 1 ] && i99=1
  [ "$i50" -gt "$nlines" ] && i50=$nlines
  [ "$i95" -gt "$nlines" ] && i95=$nlines
  [ "$i99" -gt "$nlines" ] && i99=$nlines
  p50=$(sed -n "${i50}p" "$OUT/lat_sorted_$TS.txt")
  p95=$(sed -n "${i95}p" "$OUT/lat_sorted_$TS.txt")
  p99=$(sed -n "${i99}p" "$OUT/lat_sorted_$TS.txt")
fi

# Duty-cycle estimate at INTERVAL=3s: p50_ms / 3000
duty="n/a"
if [ "$p50" -gt 0 ] 2>/dev/null; then
  duty=$(awk -v p="$p50" 'BEGIN{printf "%.4f", p/3000.0}')
fi

{
  echo "samples=$N ok=$ok_n"
  echo "lat_ms_min=$min p50=$p50 p95=$p95 p99=$p99 max=$max"
  echo "poll_interval_s=3"
  echo "duty_cycle_est_p50=$duty  # p50_ms/3000"
  echo "note=CPU/power: duty-cycle proxy only; no external ammeter"
} | tee "$SUM"
log "=== done $SUM ==="
cat "$SUM"
