# 故障注入笔记（板端手工）

## P0-1 休眠/唤醒
- `adb shell input keyevent 26` 电源键灭屏（不一定真 suspend）
- 或 `echo mem > /sys/power/state`（需权限，可能被 Android 拦）
- 注入前后跑 `collect_hg0.sh`，观察 flags 是否掉 IFF_UP（bit0）
- 重点对照：`halow_net_watch` kmsg 是否打出 `hg0 down, rebind`

## P0-3 USB 重枚举
- `ls /sys/bus/usb/devices/` 找 TXW8301
- `echo $dev > unbind; sleep 1; echo $dev > bind`
- 记录 dmesg 与 hg0 是否重建

## 观测点
- `halow_net_watch` kmsg
- `/proc/hgicf/status` 的 TX_FAIL / FLAGS
- `getprop | grep halow`

## 每轮
1. `snap_status.sh /data/local/tmp/snap_before.txt`
2. 后台 `collect_hg0.sh 172.16.0.100 1 /data/local/tmp/hg0_log.csv`
3. 注入
4. 等待恢复或 120s 超时
5. `snap_status.sh /data/local/tmp/snap_after.txt`
