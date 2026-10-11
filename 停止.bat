@echo off
chcp 65001 >nul
title 考研平台 · 停止服务
cd /d "%~dp0"
set "BACKEND=%~dp0backend-main-fastapi"
set "PIDFILE=%BACKEND%\data\server.pid"
set "PORT=8000"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"PORT=" "%BACKEND%\.env" 2^>nul`) do set "PORT=%%b"
set "PORT=%PORT: =%"
if "%PORT%"=="" set "PORT=8000"

echo ============================================================
echo   停止考研学习平台服务
echo ============================================================
echo.

if exist "%PIDFILE%" (
    set /p _pid=<"%PIDFILE%"
    echo [1/2] 停止后台服务 PID=!_pid!
    taskkill /PID !_pid! /F >nul 2>&1
    del "%PIDFILE%" >nul 2>&1
) else (
    echo [1/2] 无后台服务记录
)

echo [2/2] 检查占用 %PORT% 端口的进程
set "_found=0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    set "_found=1"
    echo       停止 PID=%%p
    taskkill /PID %%p /F >nul 2>&1
)
if "!_found!"=="0" echo       端口未被占用

echo.
echo [OK] 已停止
ping -n 4 127.0.0.1 >nul
exit /b 0
