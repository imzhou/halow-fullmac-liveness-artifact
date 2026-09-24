#!/system/bin/sh
# E4: kill oneshot watchdog + force hg0 DOWN.
# Modes:
#   stock — wait passively (expect self_heal=0)
#   lhr   — after inject, run pull/rebind supervisor independent of oneshot watch
#
# Usage:
#   run_e4_watchdog.sh [timeout_s] [outdir] [stock|lhr]

TO=${1:-25}
OUT=${2:-/data/local/tmp/e4}
MODE=${3:-stock}
IF=${IF:-hg0}
INTERVAL=${INTERVAL:-3}
WATCH_NAME=halow_net_watch
mkdir -p "$OUT"
TS=$(date +%Y%m%d_%H%M%S)
LOG="$OUT/e4_${MODE}_$TS.log"
CSV="$OUT/e4_${MODE}_$TS.csv"
VER="$OUT/e4_${MODE}_$TS.verdict"

log() { echo "[E4/$MODE] $*"; echo "$*" >> "$LOG"; }

echo "t,phase,flags,watch_alive,note" > "$CSV"

# Fast: never walk /proc/*/cmdline (hangs on busy Android).
# Process is often "sh .../halow_net_watch.sh" — match ARGS via ps -f.
watch_alive() {
  if ps -A -f 2>/dev/null | grep -q "[h]alow_net_watch"; then return 0; fi
  if ps -Af 2>/dev/null | grep -q "[h]alow_net_watch"; then return 0; fi
  if ps -A 2>/dev/null | grep -q "[h]alow_net_watch"; then return 0; fi
  if command -v pidof >/dev/null 2>&1; then
    pidof "$WATCH_NAME" >/dev/null 2>&1 && return 0
  fi
  return 1
}

kill_watch() {
  log "kill_watch: start"
  killall "$WATCH_NAME" 2>/dev/null || true
  pids=$(ps -A -f 2>/dev/null | grep "[h]alow_net_watch" | awk '{print $2}')
  [ -z "$pids" ] && pids=$(ps -Af 2>/dev/null | grep "[h]alow_net_watch" | awk '{print $2}')
  [ -z "$pids" ] && pids=$(ps -A 2>/dev/null | grep "[h]alow_net_watch" | awk '{print $2}')
  for pid in $pids; do
    kill -9 "$pid" 2>/dev/null || true
  done
  log "kill_watch: done"
}

snap() {
  phase=$1
  flags=$(cat /sys/class/net/$IF/flags 2>/dev/null || echo 0)
  if watch_alive; then wa=1; else wa=0; fi
  echo "$(date +%s),$phase,$flags,$wa," >> "$CSV"
  log "phase=$phase flags=$flags watch=$wa"
}

ensure_watch() {
  if watch_alive; then return 0; fi
  log "ensure_watch: starting via setprop"
  setprop ctl.start "$WATCH_NAME" 2>/dev/null || true
  sleep 2
  if watch_alive; then return 0; fi
  return 1
}

log "=== E4 MODE=$MODE TO=$TO ==="

ip link set "$IF" up 2>/dev/null || ifconfig "$IF" up 2>/dev/null || true
ip addr replace 172.16.0.1/24 dev "$IF" 2>/dev/null || true
ensure_watch || true
snap baseline

if [ "$MODE" = "stock" ] && ! watch_alive; then
  log "INCONCLUSIVE: baseline watch=0 (cannot test oneshot kill)"
  echo "self_heal=-1 mode=$MODE status=INCONCLUSIVE reason=no_watch_at_baseline" > "$VER"
  log "=== E4 done $(cat $VER) ==="
  setprop ctl.start "$WATCH_NAME" 2>/dev/null || true
  exit 0
fi

kill_watch
sleep 1
snap after_kill

ip link set "$IF" down 2>/dev/null || ifconfig "$IF" down 2>/dev/null || true
t0=$(date +%s)
snap injected

healed=0
while true; do
  now=$(date +%s)
  elapsed=$((now - t0))
  flags=$(cat /sys/class/net/$IF/flags 2>/dev/null || echo 0)
  up=$((flags & 1))

  if [ "$MODE" = "lhr" ] && [ "$up" -eq 0 ]; then
    log "LHR act: rebind + link up (watch still dead)"
    ip link set "$IF" up 2>/dev/null || ifconfig "$IF" up 2>/dev/null || true
    ip addr replace 172.16.0.1/24 dev "$IF" 2>/dev/null || true
    setprop vendor.a133.halow.rebind_net 1 2>/dev/null || true
    hgpriv "$IF" get sta_count >/dev/null 2>&1 || true
  fi

  flags=$(cat /sys/class/net/$IF/flags 2>/dev/null || echo 0)
  up=$((flags & 1))
  if [ "$MODE" = "stock" ] && watch_alive; then
    log "WARN: watch alive again during stock wait"
  fi
  log "wait ${elapsed}/${TO}s up=$up"
  if [ "$up" -ne 0 ]; then
    healed=1
    log "SELF_HEAL=1 at ${elapsed}s"
    break
  fi
  if [ "$elapsed" -ge "$TO" ]; then
    log "SELF_HEAL=0 timeout=${TO}s"
    break
  fi
  sleep "$INTERVAL"
done

echo "self_heal=$healed mode=$MODE" > "$VER"
log "=== E4 done $(cat $VER) ==="

log "post-test restore"
ip link set "$IF" up 2>/dev/null || ifconfig "$IF" up 2>/dev/null || true
ip addr replace 172.16.0.1/24 dev "$IF" 2>/dev/null || true
setprop vendor.a133.halow.rebind_net 1 2>/dev/null || true
setprop ctl.start "$WATCH_NAME" 2>/dev/null || true
sleep 2
