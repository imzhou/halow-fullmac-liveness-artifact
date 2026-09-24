@echo off
setlocal EnableExtensions
REM Hard recover HaLow after FWCTRL No Response.
REM Usage: restore_halow_hard.bat

cd /d "%~dp0"
set "SCRIPTS=%~dp0.."
set "ADB=adb"
if /I "%~1"=="-s" (
  set "ADB=adb -s %~2"
)

echo == push restore_halow_hard.sh ==
%ADB% push "%SCRIPTS%\restore_halow_hard.sh" /data/local/tmp/halow_exp/restore_halow_hard.sh
%ADB% shell "chmod 755 /data/local/tmp/halow_exp/restore_halow_hard.sh"

echo == run hard restore (may take ~30s) ==
%ADB% shell "sh /data/local/tmp/halow_exp/restore_halow_hard.sh"

echo == if still dead, reboot ==
echo adb reboot
exit /b 0
