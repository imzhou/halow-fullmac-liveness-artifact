@echo off
setlocal EnableExtensions
REM Measure hgpriv sta_count latency (LHR pull overhead).
REM Usage: measure_overhead.bat [N_samples]

cd /d "%~dp0"
set "SCRIPTS=%~dp0.."
set "REPO=%~dp0..\.."
set "DEVICE_BASE=/data/local/tmp/halow_exp"
set "ADB=adb"
set "N=100"
if not "%~1"=="" set "N=%~1"

echo == push measure_lhr_overhead.sh ==
%ADB% push "%SCRIPTS%\measure_lhr_overhead.sh" "%DEVICE_BASE%/measure_lhr_overhead.sh"
%ADB% shell "chmod 755 %DEVICE_BASE%/measure_lhr_overhead.sh"

echo == run N=%N% ==
%ADB% shell "sh %DEVICE_BASE%/measure_lhr_overhead.sh %N% %DEVICE_BASE%/overhead"

set "STAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%"
set "STAMP=%STAMP: =0%"
set "OUTHOST=%REPO%\board_results\overhead_%STAMP%"
mkdir "%OUTHOST%" 2>nul
echo == pull ==
%ADB% pull "%DEVICE_BASE%/overhead" "%OUTHOST%"
echo Host: %OUTHOST%
exit /b 0
