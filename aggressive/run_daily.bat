@echo off
REM ============================================================
REM  r1000 Aggressive Engine - Daily Review
REM  Called by Windows Task Scheduler (or manually)
REM
REM  Default: DRY-RUN mode (signal + plan only, no real orders)
REM  To enable live paper orders: set AGGRESSIVE_EXECUTE=1 or edit below
REM ============================================================

setlocal

REM Change to engine root directory
cd /d "H:\codex\tmp_r1000_quant_engine"

REM Timestamp for log filename
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "TS=%dt:~0,4%%dt:~4,2%%dt:~6,2%_%dt:~8,2%%dt:~10,2%"

REM Log dir
set "LOG_DIR=aggressive\state\scheduler_logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Build command based on mode
set "CMD_ARGS="
if "%AGGRESSIVE_EXECUTE%"=="1" (
    set "CMD_ARGS=--execute"
    echo [%date% %time%] LIVE EXECUTION MODE >> "%LOG_DIR%\daily_%TS%.log"
) else (
    echo [%date% %time%] DRY-RUN MODE >> "%LOG_DIR%\daily_%TS%.log"
)

REM Run daily_review
py -3 aggressive\daily_review.py --universe r1000 --top 12 %CMD_ARGS% >> "%LOG_DIR%\daily_%TS%.log" 2>&1

REM Exit code logging
if errorlevel 1 (
    echo [%date% %time%] FAILED exit code %errorlevel% >> "%LOG_DIR%\daily_%TS%.log"
    exit /b %errorlevel%
)

echo [%date% %time%] SUCCESS >> "%LOG_DIR%\daily_%TS%.log"
endlocal
exit /b 0
