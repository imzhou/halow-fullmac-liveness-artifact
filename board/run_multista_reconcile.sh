#!/system/bin/sh
# Multi-STA / reconcile experiment (E-MS + E-R).
# Stock: after disruption, sta_count may diverge from reachable peers; no heal.
# LHR mode: periodic hgpriv sta_count vs pingable peers → setprop rebind / log mismatch.
#
# Usage:
#   run_multista_reconcile.sh stock <peer1> [peer2...] 
#   run_multista_reconcile.sh lhr   <peer1> [peer2...]
# Env: TIMEOUT=40 INTERVAL=3 IF=hg0 OUTDIR=/data/local/tmp/ems
# (suite exports INTERVAL=3; do not drift back to 5)

MODE=${1:-stock}
shift
if [ $# -lt 1 ]; then
  echo "usage: $0 stock|lhr <peer_ip> [peer_ip...]"
  exit 1
fi

TIMEOUT=${TIMEOUT:-40}
INTERVAL=${INTERVAL:-3}
IF=${IF:-hg0}
OUTDIR=${OUTDIR:-/data/local/tmp/ems}
HGPRIV=${HGPRIV:-hgpriv}
mkdir -p "$OUTDIR"
TS=$(date +%Y%m%d_%H%M%S)
LOG="$OUTDIR/ems_${MODE}_$TS.log"
CSV="$OUTDIR/ems_${MODE}_$TS.csv"

log() { echo "[EMS] $*"; echo "$*" >> "$LOG"; }

count_alive() {
  n=0
  for p in "$@"; do
    if ping -c 1 -W 1 "$p" >/dev/null 2>&1; then n=$((n+1)); fi
  done
  echo "$n"
}

get_sta_count() {
  # Parse RESP from hgpriv; fall back to -1. Cap wait with timeout if present.
  if command -v timeout >/dev/null 2>&1; then
    out=$(timeout 5 $HGPRIV "$IF" get sta_count 2>/dev/null || true)
  else
    out=$($HGPRIV "$IF" get sta_count 2>/dev/null || true)
  fi
  echo "$out" | tr -cd '0-9\n' | grep -E '^[0-9]+$' | tail -1
}

echo "t,mode,alive,sta_count,mismatch,action" > "$CSV"
log "=== EMS mode=$MODE peers=$* ==="

# Baseline
alive=$(count_alive "$@")
sc=$(get_sta_count); [ -z "$sc" ] && sc=-1
echo "$(date +%s),$MODE,$alive,$sc,0,baseline" >> "$CSV"
log "baseline alive=$alive sta_count=$sc"

# Inject: bounce iface to provoke host reinit / STA table loss (best-effort without FW rebuild)
log "inject: ip link down/up $IF (provokes control-plane churn)"
ip link set "$IF" down 2>/dev/null || true
sleep 2
ip link set "$IF" up 2>/dev/null || true
# restore addr commonly used on product
ip addr replace 172.16.0.1/24 dev "$IF" 2>/dev/null || true
sleep 3

t0=$(date +%s)
mismatch_seen=0
healed=0

while true; do
  now=$(date +%s)
  elapsed=$((now - t0))
  alive=$(count_alive "$@")
  sc=$(get_sta_count); [ -z "$sc" ] && sc=-1
  mis=0
  if [ "$sc" -ge 0 ] 2>/dev/null; then
    if [ "$alive" -ne "$sc" ]; then mis=1; mismatch_seen=1; fi
  fi
  action=none
  if [ "$MODE" = "lhr" ] && [ "$mis" -eq 1 ]; then
    action=reconcile_rebind
    # Pull-based recovery: poke Android rebind path + log
    setprop vendor.a133.halow.rebind_net 1 2>/dev/null || true
    log "LHR reconcile: alive=$alive sta_count=$sc → rebind_net=1"
  fi
  echo "$(date +%s),$MODE,$alive,$sc,$mis,$action" >> "$CSV"
  log "t=${elapsed}s alive=$alive sta_count=$sc mis=$mis"

  # Heal criterion: counts agree and at least one peer alive (or all peers match expectation)
  if [ "$mis" -eq 0 ] && [ "$alive" -ge 1 ]; then
    if [ "$mismatch_seen" -eq 1 ] || [ "$MODE" = "stock" ]; then
      # stock: if never mismatched, still OK if stable; for verdict we care post-inject consistency
      healed=1
    fi
  fi

  # For stock: success if consistent; failure if mismatch persists to timeout
  if [ "$elapsed" -ge "$TIMEOUT" ]; then
    break
  fi
  sleep "$INTERVAL"
done

# Final verdict
alive=$(count_alive "$@")
sc=$(get_sta_count); [ -z "$sc" ] && sc=-1
mis=0
[ "$sc" -ge 0 ] 2>/dev/null && [ "$alive" -ne "$sc" ] && mis=1

if [ "$mis" -eq 1 ]; then
  self_heal=0
else
  self_heal=1
fi

echo "self_heal=$self_heal mismatch_final=$mis alive=$alive sta_count=$sc mode=$MODE" \
  | tee "$OUTDIR/ems_${MODE}_$TS.verdict" | tee -a "$LOG"
log "=== EMS done ==="
