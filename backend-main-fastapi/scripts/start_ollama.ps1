# 启动本地 Ollama 服务（知识点抽取 / AI 问答都依赖它）。
# 用法：右键「使用 PowerShell 运行」，或双击同目录下 start_ollama.bat
#
# 为什么需要这个脚本：`services/kp_extract.py` 100% 依赖 127.0.0.1:11434，
# 且没有降级路径 —— Ollama 没起来时知识点抽取会静默全败（knowledge_points 恒为 0）。

$ErrorActionPreference = "Stop"
$exe = "C:\Users\33884\AppData\Local\Programs\Ollama\ollama.exe"

if (-not (Test-Path $exe)) {
    Write-Host "未找到 ollama.exe：$exe" -ForegroundColor Red
    exit 1
}

# 模型缓存目录（67GB 在 D 盘，别让它跑到 C 盘）
$env:OLLAMA_MODELS = "D:\ollama-models"

$alive = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
if ($alive) {
    Write-Host "Ollama 已在运行（端口 11434 已监听），无需重复启动。" -ForegroundColor Yellow
} else {
    Write-Host "启动 Ollama serve ..."
    Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden
}

# 等待就绪
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
        Write-Host "Ollama 就绪，可用模型：" -ForegroundColor Green
        $r.models | ForEach-Object { "  - " + $_.name }
        exit 0
    } catch {
        # 继续等
    }
}

Write-Host "等待 30s 后仍未就绪，请检查 ollama serve 日志。" -ForegroundColor Red
exit 1
