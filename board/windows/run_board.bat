@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM HaLow board runner. Live adb output.
REM Usage:
REM   run_board.bat snap
REM   run_board.bat 5 172.16.0.100
REM   run_board.bat 5 172.16.0.100 172.16.0.101
REM Prefer >=2 peers for Claim-2 multi-STA board check.

cd /d "%~dp0"
set "SCRIPTS=%~dp0.."
set "REPO=%~dp0..\.."
set "DEVICE_BASE=/data/local/tmp/halow_exp"
set "ADB=adb"
set "SNAPONLY=0"
set "N=5"
set "PEERS="
set "N_SET="

:parse
if "%~1"=="" goto parsed
if /I "%~1"=="snap" (
  set "SNAPONLY=1"
  shift
  goto parse
)
if /I "%~1"=="-s" (
  if "%~2"=="" (
    echo ERROR: -s needs serial
    exit /b 1
  )
  set "ADB=adb -s %~2"
  shift
  shift
  goto parse
)
echo %~1| findstr /R "^[0-9][0-9]*$" >nul
if not errorlevel 1 (
  if "!N_SET!"=="" (
    set "N=%~1"
    set "N_SET=1"
    shift
    goto parse
  )
)
if "!PEERS!"=="" (
  set "PEERS=%~1"
) else (
  set "PEERS=!PEERS! %~1"
)
shift
goto parse

:parsed
if "!PEERS!"=="" set "PEERS=172.16.0.100"

set "HH=%time:~0,2%"
set "HH=%HH: =0%"
set "STAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%HH%%time:~3,2%%time:~6,2%"
set "STAMP=%STAMP:/=%"
set "STAMP=%STAMP:-=%"
set "STAMP=%STAMP: =0%"
if "!STAMP!"=="" set "STAMP=run_%RANDOM%"
set "OUTHOST=%REPO%\board_results\!STAMP!"
mkdir "%OUTHOST%" 2>nul
mkdir "%OUTHOST%\raw" 2>nul

echo == adb devices ==
adb devices
adb devices | findstr /R "device$" | findstr /V "List" >nul
if errorlevel 1 (
  echo ERROR: no adb device in device state.
  exit /b 1
)

echo == push scripts ==
%ADB% shell "mkdir -p %DEVICE_BASE%"
if errorlevel 1 exit /b 1

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
  echo push %%F
  %ADB% push "%SCRIPTS%\%%F" "%DEVICE_BASE%/%%F"
  if errorlevel 1 exit /b 1
)
%ADB% shell "chmod 755 %DEVICE_BASE%/*.sh"

if "%SNAPONLY%"=="1" (
  echo == snap only ==
  %ADB% shell "sh %DEVICE_BASE%/snap_status.sh %DEVICE_BASE%/snap.txt"
  %ADB% pull "%DEVICE_BASE%/snap.txt" "%OUTHOST%\snap.txt"
  echo Wrote %OUTHOST%\snap.txt
  exit /b 0
)

echo == run suite N=%N% peers=%PEERS% ==
echo Includes E4 stock + E4 LHR + EMS stock + EMS LHR. E2 off.
echo Prefer two camera IPs, e.g. 172.16.0.100 172.16.0.101
echo.

%ADB% shell "N_REPEAT=%N% E4_TO=25 EMS_TO=40 RUN_E2=0 sh %DEVICE_BASE%/run_suite.sh %DEVICE_BASE% %PEERS%"

echo.
echo == pull device results ==
set "LIST=%TEMP%\halow_results_list.txt"
%ADB% shell "ls -d %DEVICE_BASE%/results_* 2>/dev/null" > "%LIST%" 2>nul

for /f "usebackq delims=" %%R in ("%LIST%") do (
  set "REMOTE=%%R"
  set "REMOTE=!REMOTE: =!"
  if not "!REMOTE!"=="" (
    for %%N in ("!REMOTE!") do set "RNAME=%%~nxN"
    echo pull !REMOTE!
    mkdir "%OUTHOST%\raw\!RNAME!" 2>nul
    %ADB% pull "!REMOTE!" "%OUTHOST%\raw\!RNAME!"
  )
)

for /r "%OUTHOST%\raw" %%V in (*.verdict) do (
  copy /Y "%%V" "%OUTHOST%\" >nul
)

echo == done ==
echo Host results: %OUTHOST%
exit /b 0
