@echo off
chcp 65001 >nul
echo ============================================================
echo 考研学习平台 - 本地模型 LoRA 微调训练
echo ============================================================
echo.

set PYY_PYTHON=C:\Users\33884\.conda\envs\pyy\python.exe
rem 路径由 bat 自身位置推导，不写死机器专属绝对路径（P0-B2）
set "SCRIPT_DIR=%~dp0"

echo [1/4] 检查Python环境...
"%PYY_PYTHON%" --version
if errorlevel 1 (
    echo 错误：pyy环境Python不可用
    pause
    exit /b 1
)

echo.
echo [2/4] 检查GPU...
"%PYY_PYTHON%" -c "import torch; print('CUDA可用:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '无')"
if errorlevel 1 (
    echo 警告：GPU检查失败，将使用CPU训练（非常慢）
)

echo.
echo [3/4] 准备训练数据...
cd /d "%SCRIPT_DIR%"
"%PYY_PYTHON%" lora_finetune.py --stage prepare
if errorlevel 1 (
    echo 错误：数据准备失败
    pause
    exit /b 1
)

echo.
echo [4/4] 开始LoRA微调训练...
echo 训练将在后台运行，预计2-4小时（取决于GPU）
echo 训练日志将保存到 data\lora_finetune\train.log
echo.
echo 按 Ctrl+C 可停止训练
echo.

"%PYY_PYTHON%" lora_finetune.py --stage train 2>&1 | tee data\lora_finetune\train.log

echo.
echo ============================================================
echo 训练完成！
echo ============================================================
echo.
echo 下一步：
echo   1. 合并模型：%PYY_PYTHON% lora_finetune.py --stage merge
echo   2. 导入Ollama：%PYY_PYTHON% lora_finetune.py --stage ollama
echo   3. 在平台设置中将本地模型名称改为 kaoyan-assistant
echo.
pause
