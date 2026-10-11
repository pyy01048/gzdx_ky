@echo off
REM ============================================================
REM  bge-reranker-v2-m3 CPU 微服务启动脚本
REM  端口: 8140  POST /rerank
REM ============================================================
setlocal
cd /d "%~dp0"

set HF_ENDPOINT=https://hf-mirror.com
set HF_HUB_DISABLE_XET=1

set VENV_PY=%~dp0data\venv\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo [ERROR] venv not found: %VENV_PY%
    echo Please run install script first.
    pause
    exit /b 1
)

echo [INFO] Starting bge-reranker-v2-m3 on http://127.0.0.1:8140 ...
echo [INFO] Health:  http://127.0.0.1:8140/health
echo [INFO] Rerank:   POST http://127.0.0.1:8140/rerank
echo.

"%VENV_PY%" -m uvicorn app:app --host 127.0.0.1 --port 8140 --log-level info

endlocal
