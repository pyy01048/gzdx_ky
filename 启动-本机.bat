@echo off
chcp 65001 >nul
title 考研平台 · 本机模式
cd /d "%~dp0"
set "BACKEND=%~dp0backend-main-fastapi"
set "PORT=8000"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"PORT=" "%BACKEND%\.env" 2^>nul`) do set "PORT=%%b"
set "PORT=%PORT: =%"
if "%PORT%"=="" set "PORT=8000"

netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [提示] 服务已在运行，打开浏览器...
    start "" "http://127.0.0.1:%PORT%"
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)

echo ============================================================
echo   本机模式：仅本机可访问（最安全）
echo ============================================================
echo.
cd /d "%BACKEND%"
set "HOST=127.0.0.1"
start "" cmd /c "ping -n 7 127.0.0.1 >nul & start "" "http://127.0.0.1:%PORT%""
python main.py
