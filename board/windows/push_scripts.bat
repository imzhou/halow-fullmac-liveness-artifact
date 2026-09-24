@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Only push .sh scripts to tablet (no run)
REM Usage:
REM   push_scripts.bat
REM   push_scripts.bat -s SERIAL

cd /d "%~dp0"
set "SCRIPTS=%~dp0.."
set "DEVICE_BASE=/data/local/tmp/halow_exp"
set "ADB=adb"

if /I "%~1"=="-s" (
  if "%~2"=="" (
    echo ERROR: -s needs serial
    exit /b 1
  )
  set "ADB=adb -s %~2"
)

echo == adb devices ==
adb devices
adb devices | findstr /R "device$" | findstr /V "List" >nul
if errorlevel 1 (
  echo ERROR: no adb device.
  exit /b 1
)

echo == mkdir %DEVICE_BASE% ==
%ADB% shell "mkdir -p %DEVICE_BASE%"
if errorlevel 1 exit /b 1

echo == push from %SCRIPTS% ==
for %%F in (
  run_e4_watchdog.sh
  run_multista_reconcile.sh
  run_e2_sleep.sh
  run_suite.sh
  snap_status.sh
  collect_hg0.sh
  restore_halow_hard.sh
) do (
  if not exist "%SCRIPTS%\%%F" (
    echo ERROR: missing %SCRIPTS%\%%F
    exit /b 1
  )
  echo   %%F
  %ADB% push "%SCRIPTS%\%%F" "%DEVICE_BASE%/%%F"
  if errorlevel 1 (
    echo ERROR: push %%F failed
    exit /b 1
  )
)

echo == chmod ==
%ADB% shell "chmod 755 %DEVICE_BASE%/*.sh"
if errorlevel 1 exit /b 1

echo == verify ==
%ADB% shell "ls -l %DEVICE_BASE%"

echo DONE. On device: %DEVICE_BASE%
exit /b 0
