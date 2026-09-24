# Fault injection notes (manual, on the board)

## P0-1: sleep/wake

- `adb shell input keyevent 26` turns the screen off (not necessarily a real suspend)
- Or `echo mem > /sys/power/state` (needs permission; Android may block it)
- Run `collect_hg0.sh` before and after injection and watch whether flags drop IFF_UP (bit0)
- Key comparison: does `halow_net_watch` log `hg0 down, rebind` to kmsg?

## P0-3: USB re-enumeration

- `ls /sys/bus/usb/devices/` to find the TXW8301
- `echo $dev > unbind; sleep 1; echo $dev > bind`
- Record dmesg and whether hg0 is rebuilt

## Watch points

- `halow_net_watch` kmsg lines
- TX_FAIL / FLAGS in `/proc/hgicf/status`
- `getprop | grep halow`

## Per round

1. `snap_status.sh /data/local/tmp/snap_before.txt`
2. Background `collect_hg0.sh 172.16.0.100 1 /data/local/tmp/hg0_log.csv`
3. Inject
4. Wait for recovery or the 120 s timeout
5. `snap_status.sh /data/local/tmp/snap_after.txt`
