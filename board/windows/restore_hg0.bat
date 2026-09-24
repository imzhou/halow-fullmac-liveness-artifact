@echo off
setlocal EnableExtensions
REM Soft restore hg0 (up/IP/rebind/watch/clear sleep).
REM If dmesg shows FWCTRL No Response, use restore_halow_hard.bat instead.

cd /d "%~dp0"
set "ADB=adb"
if /I "%~1"=="-s" set "ADB=adb -s %~2"

echo == soft restore ==
%ADB% shell "hgpriv hg0 set sleep=0,0; ip link set hg0 up; ip addr replace 172.16.0.1/24 dev hg0; ip route replace 172.16.0.0/24 dev hg0 table 100; setprop vendor.a133.halow.rebind_net 1; setprop ctl.start halow_net_watch; sleep 2; ip link show hg0; hgpriv hg0 get conn_state; hgpriv hg0 get sta_count; dmesg | grep FWCTRL | tail -5"

echo If you see No Response, run restore_halow_hard.bat
exit /b 0
