@echo off
REM ============================================================
REM  Kaoyan Platform - Service Stopper (ASCII only)
REM  See start.bat header for why this file must stay ASCII.
REM
REM  Note: the old version used !VAR! without enabling delayed
REM  expansion, so it silently killed nothing. All logic now
REM  lives in scripts\launcher.py which is testable.
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
    echo   [ERROR] Python not found - cannot stop the service.
    echo.
    pause
    exit /b 1
)

title Kaoyan Platform - Localhost
"%PYEXE%" "%BACKEND%\scripts\launcher.py" local
echo.
pause
