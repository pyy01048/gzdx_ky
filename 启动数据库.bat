@echo off
REM ============================================================
REM  Kaoyan Platform - PostgreSQL Starter (ASCII only)
REM
REM  IMPORTANT: keep this file 100% ASCII (see start.bat header).
REM  Real work happens in scripts\startup_manager.py.
REM
REM  Usage:
REM      start-db.bat           ensure database is up (safe to re-run)
REM      start-db.bat diagnose  read-only check
REM      start-db.bat stop      graceful shutdown
REM ============================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0"
set "BACKEND=%~dp0backend-main-fastapi"

set "PYEXE="
for %%P in (
    "D:\Anaconda\python.exe"
    "C:\Users\%USERNAME%\Anaconda3\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "C:\Users\%USERNAME%\miniconda3\python.exe"
    "C:\ProgramData\Anaconda3\python.exe"
) do (
    if not defined PYEXE (
        if exist "%%~P" set "PYEXE=%%~P"
    )
)
if not defined PYEXE (
    where python >nul 2>&1
    if !errorlevel!==0 set "PYEXE=python"
)

if not defined PYEXE (
    echo.
    echo   [ERROR] Python not found - cannot control PostgreSQL.
    echo   Expected D:\Anaconda\python.exe or python on PATH.
    echo.
    pause
    exit /b 1
)

set "MGR=%BACKEND%\scripts\startup_manager.py"
if not exist "%MGR%" (
    echo.
    echo   [ERROR] missing %MGR%
    echo.
    pause
    exit /b 1
)

set "ACTION=ensure-db"
if /i "%~1"=="diagnose" set "ACTION=diagnose"
if /i "%~1"=="stop"     set "ACTION=stop-db"

title Kaoyan Platform - Database
"%PYEXE%" "%MGR%" %ACTION%
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
