#!/vendor/bin/sh
# Sample HaLow link health; append CSV rows.
# Usage: collect_hg0.sh [peer_ip] [interval_s] [outfile]
PEER=${1:-172.16.0.100}
INT=${2:-1}
OUT=${3:-/data/local/tmp/hg0_log.csv}
echo "ts,hg0_exists,flags,operstate,peer_rtt_ms,peer_loss" > "$OUT"
while true; do
  ts=$(date +%s 2>/dev/null || echo 0)
  if [ -d /sys/class/net/hg0 ]; then
    ex=1
    flags=$(cat /sys/class/net/hg0/flags 2>/dev/null)
    oper=$(cat /sys/class/net/hg0/operstate 2>/dev/null)
  else
    ex=0
    flags=0
    oper=missing
  fi
  pr=$(ping -c 3 -W 1 "$PEER" 2>/dev/null)
  rtt=$(echo "$pr" | grep -o 'time=[0-9.]*' | tail -1 | cut -d= -f2)
  loss=$(echo "$pr" | grep -o '[0-9]*% packet loss' | head -1 | cut -d% -f1)
  [ -z "$rtt" ] && rtt=-1
  [ -z "$loss" ] && loss=100
  echo "$ts,$ex,$flags,$oper,$rtt,$loss" >> "$OUT"
  sleep "$INT"
done
