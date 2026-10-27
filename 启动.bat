@echo off
REM ============================================================
REM  Kaoyan Platform - Launcher Starter (ASCII only)
REM
REM  IMPORTANT: keep this file 100% ASCII.
REM  cmd.exe cannot reliably parse multi-byte UTF-8 in .bat files -
REM  a Chinese line may be cut mid-character and silently swallow
REM  the NEXT line (verified: "echo A-OK" never ran). Adding a BOM
REM  makes it worse. All human-facing Chinese text lives in
REM  scripts\launcher.py, which prints real UTF-8 safely.
REM
REM  Usage:
REM      start.bat              interactive menu
REM      start.bat local        start backend (localhost only)
REM      start.bat lan          start backend (LAN / phone access)
REM      start.bat background   start minimized, open browser
REM      start.bat dev          backend with hot reload
REM      start.bat stop         stop backend
REM      start.bat diagnose     print environment diagnosis
REM ============================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0"
set "BACKEND=%~dp0backend-main-fastapi"

REM ---- pick a Python that actually has the project deps ----
set "PYEXE="
for %%P in (
    "D:\Anaconda\python.exe"
    "C:\Users\%USERNAME%\Anaconda3\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "C:\Users\%USERNAME%\miniconda3\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe"
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
    echo   [ERROR] Python not found. Cannot start the platform.
    echo.
    echo   Expected one of:
    echo     D:\Anaconda\python.exe
    echo     %%USERPROFILE%%\anaconda3\python.exe
    echo   ...or add python to PATH.
    echo.
    pause
    exit /b 1
)

if not exist "%BACKEND%\scripts\launcher.py" (
    echo.
    echo   [ERROR] launcher missing: %BACKEND%\scripts\launcher.py
    echo.
    pause
    exit /b 1
)

title Kaoyan Platform Launcher
if "%~1"=="" (
    "%PYEXE%" "%BACKEND%\scripts\launcher.py"
) else (
    "%PYEXE%" "%BACKEND%\scripts\launcher.py" %*
)
pause
