@echo off
REM ============================================================
REM  Kaoyan Platform - PostgreSQL Stopper (ASCII only)
REM  See start.bat header for why this file must stay ASCII.
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

title Kaoyan Platform - Stop Database
if defined PYEXE (
    "%PYEXE%" "%BACKEND%\scripts\startup_manager.py" stop-db
) else (
    set "PGBIN=D:\pgsql\pgenv\Library\bin"
    set "PGDATA=D:\pgsql\data"
    if exist "!PGBIN!\pg_ctl.exe" (
        "!PGBIN!\pg_ctl.exe" -D "!PGDATA!" -m fast stop
    ) else (
        echo   [ERROR] no Python and no pg_ctl - cannot stop database.
    )
)
echo.
pause
