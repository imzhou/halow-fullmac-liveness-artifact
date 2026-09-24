#!/vendor/bin/sh
# One-shot snapshot for paper figures.
OUT=${1:-/data/local/tmp/hg0_snap.txt}
{
  echo "==== date ===="
  date
  echo "==== hg0 ===="
  ls -l /sys/class/net/hg0 2>&1
  ip link show hg0 2>&1
  ip addr show hg0 2>&1
  echo "==== proc status ===="
  cat /proc/hgicf/status 2>&1
  echo "==== hgpriv sta_count ===="
  hgpriv hg0 get sta_count 2>&1
  echo "==== hgpriv conn_state / signal ===="
  hgpriv hg0 get conn_state 2>&1
  hgpriv hg0 get signal 2>&1
  echo "==== props ===="
  getprop | grep -iE 'halow|hgic|hg0' 2>&1
  echo "==== watch process ===="
  pgrep -af halow_net_watch 2>&1
  echo "==== leases ===="
  cat /data/vendor/dhcp/dnsmasq.leases 2>/dev/null
} > "$OUT"
echo wrote "$OUT"
