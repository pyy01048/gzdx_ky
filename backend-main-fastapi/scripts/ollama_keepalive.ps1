# Ollama 守护：端口 11434 没监听就拉起 ollama serve。
# 为什么要走「计划任务」：直接用 Start-Process 起的 ollama 属于当前终端会话，
# 会话一结束就整棵进程树被回收（实测 8~20 分钟必死），知识点抽取随之全败。
# 计划任务由 Task Scheduler 服务托管，脱离交互会话，不会被回收。
$ErrorActionPreference = 'SilentlyContinue'

$env:OLLAMA_MODELS = 'D:\ollama-models'
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS', 'D:\ollama-models', 'User')

$exe = 'C:\Users\33884\AppData\Local\Programs\Ollama\ollama.exe'
if (-not (Test-Path $exe)) { exit 1 }

$listening = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
if ($listening) { exit 0 }   # 已存活，什么都不做

Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden
exit 0
