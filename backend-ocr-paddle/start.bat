@echo off
chcp 65001 >nul
title PaddleOCR PP-OCRv5 文字识别服务
echo ============================================
echo    PaddleOCR PP-OCRv5 文字识别服务
echo    http://127.0.0.1:8888
echo ============================================
echo.

cd /d "%~dp0"

REM ---- 检测端口是否已被占用 ----
netstat -ano | findstr ":8888 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [提示] 检测到端口 8888 已有服务在运行，跳过启动。
    echo 直接访问 http://127.0.0.1:8888
    pause
    exit /b 0
)

REM ---- 检查 Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+ 并勾选 "Add to PATH"。
    pause
    exit /b 1
)

REM ---- 安装依赖 ----
echo [1/2] 检查并安装依赖（首次运行较慢，PaddlePaddle 约 500MB）...
pip install -r requirements.txt --quiet

REM ---- 启动服务 ----
echo [2/2] 启动 PaddleOCR 服务（首次启动会下载模型，请耐心等待）...
echo.
python main.py

pause
