@echo off
REM ============================================================
REM  Weekly Theme Discovery + Full Daily Review
REM  Schedule: Sunday 11pm KST (before market week starts)
REM ============================================================

setlocal

cd /d "H:\codex\tmp_r1000_quant_engine"

for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "TS=%dt:~0,4%%dt:~4,2%%dt:~6,2%_%dt:~8,2%%dt:~10,2%"

set "LOG_DIR=aggressive\state\scheduler_logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] WEEKLY DISCOVERY START >> "%LOG_DIR%\weekly_%TS%.log"

py -3 aggressive\theme_discovery.py --universe r1000 --lookback-days 90 >> "%LOG_DIR%\weekly_%TS%.log" 2>&1

if errorlevel 1 (
    echo [%date% %time%] DISCOVERY FAILED exit code %errorlevel% >> "%LOG_DIR%\weekly_%TS%.log"
    exit /b %errorlevel%
)

echo [%date% %time%] DISCOVERY SUCCESS >> "%LOG_DIR%\weekly_%TS%.log"
endlocal
exit /b 0
