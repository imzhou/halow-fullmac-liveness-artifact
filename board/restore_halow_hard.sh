#!/system/bin/sh
# Hard recover HaLow after FWCTRL No Response / sleep hang.
# Does NOT rebuild firmware; reloads host driver + re-runs property bring-up.

echo "=== soft wake ==="
hgpriv hg0 set sleep=0,0 2>/dev/null || true
sleep 1

echo "=== check ctrl ==="
if hgpriv hg0 get conn_state 2>&1 | grep -qi "No Response\|timeout\|fail"; then
  echo "ctrl still bad, escalate"
else
  # try soft path first
  out=$(hgpriv hg0 get sta_count 2>&1 || true)
  echo "sta_count: $out"
  if echo "$out" | grep -qE "[0-9]"; then
    echo "soft OK"
    ip link set hg0 up 2>/dev/null || true
    ip addr replace 172.16.0.1/24 dev hg0 2>/dev/null || true
    setprop vendor.a133.halow.rebind_net 1
    setprop ctl.start halow_net_watch
    exit 0
  fi
fi

echo "=== USB rebind (best effort) ==="
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] || continue
  vid=$(cat "$d/idVendor" 2>/dev/null)
  # Taixin / common HaLow USB IDs — also match product string if present
  if [ "$vid" = "a69c" ] || [ "$vid" = "A69C" ] || grep -qi taixin "$d/product" 2>/dev/null || grep -qi hgic "$d/product" 2>/dev/null; then
    name=$(basename "$d")
    echo "rebind $name vid=$vid"
    echo "$name" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
    sleep 1
    echo "$name" > /sys/bus/usb/drivers/usb/bind 2>/dev/null || true
  fi
done
sleep 2

echo "=== rmmod / insmod hgicf ==="
# stop watch so it does not race
setprop ctl.stop halow_net_watch 2>/dev/null || true
ifconfig hg0 down 2>/dev/null || ip link set hg0 down 2>/dev/null || true
rmmod hgicf 2>/dev/null || rmmod hgicf.ko 2>/dev/null || true
sleep 1
# same fw name as init.device.rc
insmod /vendor/modules/hgicf.ko ifname=hg0 fw_file=txw8301_v2.4.1.5-40938_2026.3.10_USB.bin
echo "insmod ret=$?"
sleep 5

echo "=== property bring-up ==="
# edge-trigger: clear then set
setprop vendor.a133.halow.ready 0
setprop vendor.a133.halow.hgpriv_done 0
setprop vendor.a133.halow.setup_net 0
sleep 1
# if driver sets hgicf.ready itself, wait; else poke setup after delay
i=0
while [ "$i" -lt 30 ]; do
  if [ -d /sys/class/net/hg0 ]; then
    echo "hg0 appeared"
    break
  fi
  i=$((i+1))
  sleep 1
done

# re-apply AP config (same as init on hgicf.ready)
hgpriv hg0 set mode=ap 2>/dev/null || true
hgpriv hg0 set key_mgmt=WPA-PSK 2>/dev/null || true
hgpriv hg0 set bss_bw=2 2>/dev/null || true
hgpriv hg0 set chan_list=8660 2>/dev/null || true
hgpriv hg0 set ap_psmode=1 2>/dev/null || true
hgpriv hg0 set ps_mode=4 2>/dev/null || true
hgpriv hg0 set dcdc13=1 2>/dev/null || true
setprop vendor.a133.halow.hgpriv_done 1
setprop vendor.a133.halow.setup_net 1
sleep 2
setprop vendor.a133.halow.ready 1
setprop ctl.start halow_net_watch 2>/dev/null || true

echo "=== status ==="
ip link show hg0 2>&1
ip addr show hg0 2>&1
hgpriv hg0 get conn_state 2>&1
hgpriv hg0 get sta_count 2>&1
dmesg | grep -iE "FWCTRL|hgic|No Response" | tail -10
echo "DONE. If still No Response: reboot tablet."
