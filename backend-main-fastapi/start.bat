@echo off
cd /d "%~dp0"
echo 正在启动后端服务...
pip install -r requirements.txt --quiet
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
