import React, { useState, useEffect } from 'react'
import { Empty, toast, toastOk, toastErr } from '../components/UI'
import { Card } from '../components/Card'

/**
 * 模型训练管理页面
 * 提供 LoRA 微调任务的启动、监控和文档识别导入功能
 */
export default function ModelTraining() {
  const [trainingStatus, setTrainingStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showConfig, setShowConfig] = useState(false)
  const [config, setConfig] = useState({
    base_model: 'Qwen/Qwen2.5-4B-Instruct',
    num_epochs: 3,
    batch_size: 2,
    learning_rate: 2e-4,
    lora_r: 16,
    lora_alpha: 32,
    use_gpu: true,
  })

  // 加载训练状态（轮询与手动刷新共用；返回值只给手动刷新判成败，轮询期间不弹提示）
  const loadStatus = async () => {
    try {
      setLoading(true)
      const response = await fetch('/api/model-training/training/status')
      const data = await response.json()
      setTrainingStatus(data)
      return true
    } catch (e) {
      return false
    } finally {
      setLoading(false)
    }
  }

  /* 手动刷新：成功后绿色提示；失败红色提示并说明原因 */
  const refreshStatus = async () => {
    const ok = await loadStatus()
    if (ok) toastOk('训练状态已刷新')
    else toastErr('刷新失败，请检查后端服务后重试')
  }

  /* 空态行动入口：展开配置面板并滚到可见位置 */
  const openConfig = () => {
    setShowConfig(true)
    setTimeout(() => {
      const el = document.getElementById('lora-config')
      if (el) {
        try { el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) } catch (e) { /* ignore */ }
      }
    }, 60)
  }

  useEffect(() => {
    loadStatus()
    // 每 10 秒轮询一次训练状态
    const interval = setInterval(loadStatus, 10000)
    return () => clearInterval(interval)
  }, [])

  // 启动训练
  const startTraining = async () => {
    if (!confirm('确定要启动 LoRA 微调任务吗？预计需要 2-4 小时。')) {
      return
    }
    try {
      const response = await fetch('/api/model-training/training/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      const data = await response.json()
      toastOk(data.message || '训练任务已启动')
      loadStatus()
    } catch (e) {
      toastErr('启动训练失败：' + e.message)
    }
  }

  // 取消训练
  const cancelTraining = async () => {
    if (!confirm('确定要取消当前训练任务吗？')) {
      return
    }
    try {
      await fetch('/api/model-training/training/cancel', { method: 'POST' })
      toastOk('训练任务已取消')
      loadStatus()
    } catch (e) {
      toastErr('取消训练失败：' + e.message)
    }
  }

  if (loading) {
    return (
      <div className="page-head">
        <h1 className="page-title">模型训练与文档识别</h1>
        <p className="page-sub">加载中...</p>
      </div>
    )
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">模型训练与文档识别</h1>
          <p className="page-sub">LoRA 微调答疑模型 · 批量 OCR 识别 · 去手写处理 · 知识库导入</p>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={refreshStatus}>刷新</button>
          <button className="btn primary" onClick={() => setShowConfig(!showConfig)}>
            {showConfig ? '隐藏配置' : '训练配置'}
          </button>
        </div>
      </div>

      <div className="stack">
        {/* 训练状态卡片 */}
        <Card title="训练任务状态">
          {trainingStatus?.status === 'idle' ? (
            <Empty
              title="暂无训练任务"
              desc="点击下方按钮配置参数并启动 LoRA 微调任务"
              action={<button className="btn primary" onClick={openConfig}>去配置训练</button>}
            />
          ) : (
            <div>
              <div className="grid-4">
                <div className="stat-tile">
                  <div className="st-val">{trainingStatus?.status}</div>
                  <div className="st-label">当前状态</div>
                </div>
                <div className="stat-tile">
                  <div className="st-val">{trainingStatus?.progress}%</div>
                  <div className="st-label">训练进度</div>
                </div>
                <div className="stat-tile">
                  <div className="st-val">{trainingStatus?.current_epoch}/{trainingStatus?.total_epochs}</div>
                  <div className="st-label">Epoch</div>
                </div>
                <div className="stat-tile">
                  <div className="st-val">{trainingStatus?.estimated_time || '-'}</div>
                  <div className="st-label">预计剩余时间</div>
                </div>
              </div>

              {trainingStatus?.message && (
                <div style={{ marginTop: 'var(--space-3)', padding: 'var(--space-2)', background: 'var(--surface-2)', borderRadius: 'var(--radius-sm)' }}>
                  <b>最新消息：</b>{trainingStatus.message}
                </div>
              )}

              {trainingStatus?.status === 'training' && (
                <div style={{ marginTop: 'var(--space-3)' }}>
                  <button className="btn danger" onClick={cancelTraining}>取消训练</button>
                </div>
              )}
            </div>
          )}
        </Card>

        {/* 训练配置面板 */}
        {showConfig && (
          <Card title="LoRA 微调配置" id="lora-config">
            <div className="grid-2">
              <div className="field">
                <label>基座模型</label>
                <input
                  className="input"
                  type="text"
                  value={config.base_model}
                  onChange={(e) => setConfig({ ...config, base_model: e.target.value })}
                  placeholder="Qwen/Qwen2.5-4B-Instruct"
                />
              </div>
              <div className="field">
                <label>训练轮数 (Epochs)</label>
                <input
                  className="input"
                  type="number"
                  value={config.num_epochs}
                  onChange={(e) => setConfig({ ...config, num_epochs: Number(e.target.value) })}
                  min="1"
                  max="10"
                />
              </div>
              <div className="field">
                <label>批次大小 (Batch Size)</label>
                <input
                  className="input"
                  type="number"
                  value={config.batch_size}
                  onChange={(e) => setConfig({ ...config, batch_size: Number(e.target.value) })}
                  min="1"
                  max="8"
                />
              </div>
              <div className="field">
                <label>学习率</label>
                <input
                  className="input"
                  type="number"
                  step="0.00001"
                  value={config.learning_rate}
                  onChange={(e) => setConfig({ ...config, learning_rate: parseFloat(e.target.value) })}
                />
              </div>
              <div className="field">
                <label>LoRA Rank (r)</label>
                <input
                  className="input"
                  type="number"
                  value={config.lora_r}
                  onChange={(e) => setConfig({ ...config, lora_r: Number(e.target.value) })}
                  min="4"
                  max="64"
                />
              </div>
              <div className="field">
                <label>LoRA Alpha</label>
                <input
                  className="input"
                  type="number"
                  value={config.lora_alpha}
                  onChange={(e) => setConfig({ ...config, lora_alpha: Number(e.target.value) })}
                  min="8"
                  max="128"
                />
              </div>
              <div className="field" style={{ gridColumn: '1 / -1' }}>
                <label>
                  <input
                    type="checkbox"
                    checked={config.use_gpu}
                    onChange={(e) => setConfig({ ...config, use_gpu: e.target.checked })}
                  />{' '}
                  使用 GPU 加速
                </label>
              </div>
            </div>
            <div className="card-foot" style={{ justifyContent: 'flex-start' }}>
              <button className="btn primary" onClick={startTraining}>
                启动训练
              </button>
            </div>
          </Card>
        )}

        {/* 文档识别与导入 */}
        <Card title="文档识别与知识库导入">
          <div className="grid-2">
            <div>
              <h3 style={{ marginBottom: 'var(--space-2)' }}>批量 OCR 识别</h3>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--fg-2)', marginBottom: 'var(--space-2)' }}>
                对知识库中的 PDF/DOCX 文档进行 OCR 文字识别，提取可搜索内容。
              </p>
              <button
                className="btn outline"
                onClick={() => toast('请在「知识库导入」页面触发扫描')}
              >
                前往知识库导入
              </button>
            </div>

            <div>
              <h3 style={{ marginBottom: 'var(--space-2)' }}>去手写处理</h3>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--fg-2)', marginBottom: 'var(--space-2)' }}>
                移除扫描版教材/试卷上的手写笔记，保留印刷体内容，提升 OCR 准确率。
              </p>
              <button
                className="btn outline"
                onClick={() => toast('去手写功能开发中')}
                disabled
              >
                去手写处理（开发中）
              </button>
            </div>
          </div>
        </Card>

        {/* 说明文档 */}
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)', lineHeight: 1.8 }}>
          <p><b>训练流程说明：</b></p>
          <ol style={{ paddingLeft: 'var(--space-4)', margin: 'var(--space-1) 0' }}>
            <li><b>数据准备</b>：系统自动从数据库读取 SFT 样本（问答对）</li>
            <li><b>启动训练</b>：配置参数后点击"启动训练"，后台开始 LoRA 微调</li>
            <li><b>监控进度</b>：实时查看训练进度、损失曲线和预估完成时间</li>
            <li><b>合并模型</b>：训练完成后自动合并 LoRA 权重到基座模型</li>
            <li><b>部署上线</b>：新模型导入 Ollama，更新 AI 助手路由配置</li>
          </ol>

          <p style={{ marginTop: 'var(--space-2)' }}><b>注意事项：</b></p>
          <ul style={{ paddingLeft: 'var(--space-4)', margin: 'var(--space-1) 0' }}>
            <li>训练需要 GPU 支持，CPU 模式极慢（不推荐）</li>
            <li>建议至少 8GB 显存，否则可能 OOM</li>
            <li>训练期间不要关闭浏览器，否则会失去连接</li>
            <li>训练日志可在后端 logs/ 目录查看完整输出</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
