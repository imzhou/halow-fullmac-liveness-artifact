#!/system/bin/sh
# E2: try hgpriv sleep inject. If firmware rejects, write SKIP (model-only).
# Usage: run_e2_sleep.sh [sleep_type] [sleep_ms] [timeout_s]

TYPE=${1:-1}
MS=${2:-60000}
TO=${3:-90}
IF=${IF:-hg0}
HGPRIV=${HGPRIV:-hgpriv}
OUT=${OUTDIR:-/data/local/tmp/e2}
mkdir -p "$OUT"
TS=$(date +%Y%m%d_%H%M%S)
LOG="$OUT/e2_$TS.log"
VER="$OUT/e2_$TS.verdict"

log() { echo "[E2] $*"; echo "$*" >> "$LOG"; }

log "=== E2 sleep type=$TYPE ms=$MS ==="
before=$($HGPRIV "$IF" get conn_state 2>&1 || true)
log "before: $before"

resp=$($HGPRIV "$IF" set sleep=${TYPE},${MS} 2>&1 || true)
log "set sleep RESP: $resp"

# Heuristic: RESP negative / fail / not support → SKIP
echo "$resp" | grep -qiE 'fail|error|not support|invalid|RESP:-' && {
  echo "status=SKIP reason=hgpriv_sleep_rejected" | tee "$VER"
  log "SKIP - cite model + iwpriv.c:830 only"
  exit 0
}

t0=$(date +%s)
# Watch whether admin stays UP while data plane dies (ping default peer)
PEER=${PEER:-172.16.0.100}
dead=0
while true; do
  elapsed=$(( $(date +%s) - t0 ))
  flags=$(cat /sys/class/net/$IF/flags 2>/dev/null || echo 0)
  up=$((flags & 1))
  if ping -c 1 -W 1 "$PEER" >/dev/null 2>&1; then ok=1; else ok=0; fi
  log "t=${elapsed}s up=$up ping=$ok"
  if [ "$up" -eq 1 ] && [ "$ok" -eq 0 ]; then dead=1; fi
  [ "$elapsed" -ge "$TO" ] && break
  sleep 2
done

# Did stock recover without manual clear?
if [ "$dead" -eq 1 ]; then
  if ping -c 2 -W 1 "$PEER" >/dev/null 2>&1; then
    echo "status=OK self_heal=1 blackhole_observed=1" | tee "$VER"
  else
    echo "status=OK self_heal=0 blackhole_observed=1" | tee "$VER"
  fi
else
  echo "status=INCONCLUSIVE blackhole_observed=0" | tee "$VER"
fi
log "=== E2 done $(cat $VER) ==="

# mandatory wake — sleep inject often leaves FWCTRL dead
log "mandatory wake sleep=0,0"
$HGPRIV "$IF" set sleep=0,0 2>/dev/null || true
ip link set "$IF" up 2>/dev/null || true
setprop vendor.a133.halow.rebind_net 1 2>/dev/null || true
