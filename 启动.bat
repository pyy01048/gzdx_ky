@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title 考研学习平台 · 启动器

cd /d "%~dp0"
set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend-main-fastapi"
set "PIDFILE=%BACKEND%\data\server.pid"
set "LOGFILE=%BACKEND%\data\server.log"

REM ============================================================
REM  读取 .env 的 HOST / PORT（与后端保持一致）
REM ============================================================
set "PORT=8000"
set "HOST=127.0.0.1"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"PORT=" "%BACKEND%\.env" 2^>nul`) do set "PORT=%%b"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"HOST=" "%BACKEND%\.env" 2^>nul`) do set "HOST=%%b"
set "PORT=%PORT: =%"
set "HOST=%HOST: =%"
if "%HOST%"=="" set "HOST=127.0.0.1"
if "%HOST%"=="0.0.0.0" (set "URL=http://127.0.0.1:%PORT%") else (set "URL=http://127.0.0.1:%PORT%")

goto :menu

REM ============================================================
:menu
cls
echo.
echo   ============================================================
echo      考研学习平台 · 启动器
echo   ============================================================
echo.
echo      当前配置: 监听 %HOST%:%PORT%
if "%HOST%"=="0.0.0.0" (echo      局域网访问: 已开启（手机可访问）) else (echo      局域网访问: 关闭（仅本机）)
echo.
call :status
echo.
echo   ------------------------------------------------------------
echo     请选择启动方式:
echo   ------------------------------------------------------------
echo.
echo      [1]  本机模式     仅本机访问，最安全（推荐日常用）
echo      [2]  局域网模式   手机/平板可访问，显示二维码
echo      [3]  后台模式     静默启动，不占任务栏，自动开浏览器
echo      [4]  停止服务     关闭正在运行的服务
echo      [5]  打开浏览器   服务已在运行时直接用
echo      [6]  环境自检     检查 Python / 依赖 / 数据库 / 模型
echo      [7]  开发模式     前端热更新（需要 Node.js）
echo.
echo      [0]  退出
echo.
set /p "choice=  请输入编号并回车: "

if "%choice%"=="1" goto :local
if "%choice%"=="2" goto :lan
if "%choice%"=="3" goto :background
if "%choice%"=="4" goto :stop
if "%choice%"=="5" goto :openbrowser
if "%choice%"=="6" goto :selfcheck
if "%choice%"=="7" goto :dev
if "%choice%"=="0" exit /b 0
goto :menu

REM ============================================================
:running_check
REM 返回 errorlevel 0 = 已在运行
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
exit /b %errorlevel%

:status
call :running_check
if %errorlevel%==0 (
    echo      [状态] 服务正在运行  ^-^>  %URL%
) else (
    echo      [状态] 服务未运行
)
exit /b 0

REM ============================================================
:local
call :running_check
if %errorlevel%==0 (
    echo.
    echo   [提示] 服务已在运行，直接打开浏览器
    ping -n 3 127.0.0.1 >nul
    start "" "%URL%"
    goto :menu
)
echo.
echo   [1/2] 正在以本机模式启动 ...
set "HOST=127.0.0.1"
start "考研平台" cmd /k "cd /d "%BACKEND%" && set HOST=127.0.0.1 && python main.py"
call :wait_ready
goto :after_start

REM ============================================================
:lan
echo.
echo   [提示] 局域网模式会让同一 WiFi 下的设备都能访问。
echo          建议在 .env 里设置 APP_PASSWORD 以防陌生人访问。
echo.
echo   [1/3] 尝试放行防火墙端口 %PORT%（非管理员会失败，不阻塞）
netsh advfirewall firewall show rule name="KaoyanPlatform" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="KaoyanPlatform" dir=in action=allow protocol=TCP localport=%PORT% >nul 2>&1
    if !errorlevel!==0 (echo         已添加防火墙规则) else (echo         [跳过] 需要管理员权限；手机打不开时请右键本文件以管理员身份运行)
) else (
    echo         防火墙规则已存在
)
echo.
echo   [2/3] 启动服务 ...
start "考研平台" cmd /k "cd /d "%BACKEND%" && set HOST=0.0.0.0 && python main.py"
call :wait_ready
goto :after_start

REM ============================================================
:background
call :running_check
if %errorlevel%==0 (
    echo.
    echo   [提示] 服务已在运行
    start "" "%URL%"
    ping -n 3 127.0.0.1 >nul
    goto :menu
)
echo.
echo   [1/3] 后台启动（日志: backend-main-fastapi\data\server.log）
cd /d "%BACKEND%"
if not exist "data" mkdir "data"
start "" /min cmd /c "python run_server.py > "%LOGFILE%" 2>&1"
call :wait_ready
cd /d "%ROOT%"
goto :after_start

REM ============================================================
:wait_ready
echo   [..] 等待服务就绪（最多 40 秒）
set /a _n=0
:wait_loop
ping -n 2 127.0.0.1 >nul
set /a _n+=1
if exist "%BACKEND%\data\server.pid" (
    curl -s -o nul -w "" "%URL%/api/health" 2>nul && goto :ready_ok
)
curl -s "%URL%/api/health" >nul 2>&1
if %errorlevel%==0 goto :ready_ok
if %_n% lss 40 goto :wait_loop
echo   [警告] 等待超时，服务可能仍在启动中
exit /b 0
:ready_ok
echo   [OK] 服务已就绪
exit /b 0

REM ============================================================
:after_start
start "" "%URL%"
echo.
echo   ============================================================
echo     启动完成
echo     本机访问 : %URL%
call :lan_hint
echo     停止服务 : 重新运行本启动器选 [4]
echo   ============================================================
echo.
pause
goto :menu

:lan_hint
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /c:"IPv4"') do (
    set "_ip=%%i"
    set "_ip=!_ip: =!"
    echo     手机访问 : http://!_ip!:%PORT%   （需同一 WiFi）
    goto :lan_hint_done
)
:lan_hint_done
exit /b 0

REM ============================================================
:stop
echo.
if exist "%PIDFILE%" (
    set /p _pid=<"%PIDFILE%"
    echo   正在停止进程 PID=!_pid! ...
    taskkill /PID !_pid! /F >nul 2>&1
    del "%PIDFILE%" >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo   正在停止占用 %PORT% 端口的进程 PID=%%p ...
    taskkill /PID %%p /F >nul 2>&1
)
echo   [OK] 已停止
echo.
pause
goto :menu

REM ============================================================
:openbrowser
start "" "%URL%"
goto :menu

REM ============================================================
:selfcheck
echo.
cd /d "%BACKEND%"
python scripts\diagnostics\check_env.py
cd /d "%ROOT%"
echo.
pause
goto :menu

REM ============================================================
:dev
cd /d "%BACKEND%"
echo.
echo   开发模式：后端(带重载) + 前端(Vite 热更新)
echo   前端地址 http://127.0.0.1:5173
echo.
start "后端-开发" cmd /k "cd /d "%BACKEND%" && python -m uvicorn main:app --host 127.0.0.1 --port %PORT% --reload"
ping -n 4 127.0.0.1 >nul
start "前端-开发" cmd /k "cd /d "%ROOT%frontend" && npm run dev"
ping -n 7 127.0.0.1 >nul
start "" http://127.0.0.1:5173
echo   已启动。关闭两个命令行窗口即停止。
echo.
pause
cd /d "%ROOT%"
goto :menu
