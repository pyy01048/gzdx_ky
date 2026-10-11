@echo off
chcp 65001 >nul
title 考研平台 · 局域网模式（手机可访问）
cd /d "%~dp0"
set "BACKEND=%~dp0backend-main-fastapi"
set "PORT=8000"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"PORT=" "%BACKEND%\.env" 2^>nul`) do set "PORT=%%b"
set "PORT=%PORT: =%"
if "%PORT%"=="" set "PORT=8000"

echo ============================================================
echo   局域网模式：同一 WiFi 下的手机 / 平板都能访问
echo   建议在 .env 里设置 APP_PASSWORD 防止陌生人访问
echo ============================================================
echo.

echo [1/2] 放行防火墙端口 %PORT%（需管理员权限，失败不阻塞）
netsh advfirewall firewall show rule name="KaoyanPlatform" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="KaoyanPlatform" dir=in action=allow protocol=TCP localport=%PORT% >nul 2>&1
    if %errorlevel%==0 (echo       已添加防火墙规则) else (echo       [跳过] 需要管理员权限；手机打不开时请右键本文件以管理员身份运行)
) else (
    echo       防火墙规则已存在
)
echo.

echo [2/2] 启动服务（下方会打印手机访问地址与二维码）
cd /d "%BACKEND%"
set "HOST=0.0.0.0"
python show_access.py 2>nul
python main.py
