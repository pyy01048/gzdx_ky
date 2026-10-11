# -*- coding: utf-8 -*-
"""生成 .bat 启动脚本（严格无 BOM + CRLF）。

为什么用脚本生成而不用编辑器手写：
    cmd.exe **无法解析带 UTF-8 BOM 的 .bat** —— 首行会变成
    ``锘?echo off`` 或直接报 "不是内部或外部命令"。
    PowerShell 的 `Set-Content -Encoding UTF8` 在 Windows PowerShell 5.1 下
    默认**带 BOM**，所以那批脚本直接跑不起来。这里用 Python 精确控制字节。
"""

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEADER = "@echo off\nchcp 65001 >nul\n"

LOCAL = HEADER + r'''title 考研平台 · 本机模式
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
'''

LAN = HEADER + r'''title 考研平台 · 局域网模式（手机可访问）
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
'''

STOP = HEADER + r'''title 考研平台 · 停止服务
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
'''

FILES = {
    "启动-本机.bat": LOCAL,
    "启动-局域网.bat": LAN,
    "停止.bat": STOP,
}


def main() -> int:
    for name, content in FILES.items():
        path = os.path.join(ROOT, name)
        # newline="" 阻止 Python 把 \n 转成 \r\n 两次；显式写成 \r\n
        data = content.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        with open(path, "wb") as f:
            f.write(data)
        # 校验：必须是 UTF-8 且**无 BOM**
        raw = open(path, "rb").read()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        print(f"  {name:<22} {len(raw):>5} bytes  BOM={'有(错误!)' if has_bom else '无(正确)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
