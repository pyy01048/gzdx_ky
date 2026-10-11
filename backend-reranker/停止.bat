@echo off
REM 停止 reranker 服务（占用 8140 端口的进程）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8140" ^| findstr "LISTENING"') do (
    echo Killing PID %%a on port 8140 ...
    taskkill /F /PID %%a
)
echo Done.
