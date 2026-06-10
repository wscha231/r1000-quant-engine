@echo off
REM auto_sync_to_drive.bat
REM
REM Windows batch script to auto-sync cloud_results -> gdrive
REM Run via Task Scheduler hourly OR on-demand
REM
REM Setup (one-time):
REM   1. Save this file to your local repo (e.g. C:\Users\Andrew Cha\Documents\codex\tools\auto_sync_to_drive.bat)
REM   2. Open Task Scheduler (taskschd.msc)
REM   3. Create Basic Task → Name: "r1000 cloud sync"
REM   4. Trigger: Daily / Repeat every 1 hour for 24h
REM   5. Action: Start a program → Program: this .bat path
REM   6. Conditions: only run if PC is awake; wake to run = optional
REM
REM Logs to tools\auto_sync.log

setlocal
cd /d "%~dp0..\"
set LOGFILE=tools\auto_sync.log

echo ============================================== >> %LOGFILE%
echo [%date% %time%] auto_sync started >> %LOGFILE%

REM 1. Pull latest from origin
echo [%date% %time%] git pull >> %LOGFILE%
git pull origin master >> %LOGFILE% 2>&1
if errorlevel 1 (
  echo [%date% %time%] git pull FAILED >> %LOGFILE%
  exit /b 1
)

REM 2. Sync cloud_results to gdrive
echo [%date% %time%] sync_cloud_to_drive (variant) >> %LOGFILE%
py -3 tools\sync_cloud_to_drive.py --mode r1000+adr >> %LOGFILE% 2>&1

echo [%date% %time%] sync_cloud_to_drive (baseline) >> %LOGFILE%
py -3 tools\sync_cloud_to_drive.py --mode r1000 >> %LOGFILE% 2>&1

REM 3. Sync scanner / advisor / theme outputs (lighter, may be in cloud_results/scanner/ etc)
echo [%date% %time%] copying scanner outputs >> %LOGFILE%
xcopy /Y /D cloud_results\scanner\*.json "G:\내 드라이브\r1000_top30_institutional\cloud_scanner\" >nul 2>&1
xcopy /Y /D cloud_results\paper_runs\*.log "G:\내 드라이브\r1000_top30_institutional\cloud_paper_runs\" >nul 2>&1
xcopy /Y /D cloud_results\ic_monitor\*.json "G:\내 드라이브\r1000_top30_institutional\cloud_ic_monitor\" >nul 2>&1

echo [%date% %time%] auto_sync DONE >> %LOGFILE%
endlocal
exit /b 0
