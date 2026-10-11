import React, { useEffect, useMemo, useState } from 'react'
import { aiApi } from '../api/client'
import { Warning, CheckCircle, RefreshCw, Download } from '../components/Icon'

/**
 * 模型选型面板：把"该装哪个模型"从猜变成可查的事实。
 *
 * 三块内容：
 *  1. 本机硬件画像（显存决定一切）
 *  2. 分科路由建议（数学走推理型、政治走中文型）
 *  3. 全部模型档案 + 本机适配判定 + 拉取命令
 */
export default function ModelSelectPanel() {
  const [rep, setRep] = useState(null)
  const [status, setStatus] = useState('loading')
  const [tab, setTab] = useState('subject')     // subject | local | cloud
  const [copied, setCopied] = useState('')

  const load = () => {
    setStatus('loading')
    aiApi.modelCatalog()
      .then((d) => { setRep(d); setStatus('ok') })
      .catch(() => setStatus('error'))
  }

  useEffect(() => { load() }, [])

  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(text)
      setTimeout(() => setCopied(''), 1800)
    } catch {
      setCopied('FAIL')
      setTimeout(() => setCopied(''), 1800)
    }
  }

  const groups = useMemo(() => {
    if (!rep) return { local: [], cloud: [] }
    const local = rep.models.filter((m) => m.local)
    const cloud = rep.models.filter((m) => !m.local)
    // 本地按适配度排序：能跑的在前面
    const order = { perfect: 0, ok: 1, tight: 2, too_big: 3, unknown: 2 }
    local.sort((a, b) => (order[a.fit.level] ?? 9) - (order[b.fit.level] ?? 9)
      || b.reasoning - a.reasoning)
    return { local, cloud }
  }, [rep])

  if (status === 'loading') {
    return <div className="card"><div className="card-body"><div className="loading-inline">读取硬件与模型档案…</div></div></div>
  }
  if (status === 'error' || !rep) {
    return (
      <div className="card">
        <div className="card-body">
          <div className="empty-hint">读取失败，请确认后端已启动。</div>
          <button className="btn ghost" onClick={load}>重试</button>
        </div>
      </div>
    )
  }

  const hw = rep.hardware
  const tierLabel = {
    cpu: '无独显（只能走云端 API）',
    entry: '入门级显存（4-6GB）',
    mainstream: '主流级显存（6-9GB）',
    advanced: '进阶级显存（9-16GB）',
    high: '高端显存（16GB+）',
  }[rep.hardware_tier] || rep.hardware_tier

  return (
    <section className="card model-panel">
      <div className="card-head">
        <div>
          <div className="card-title">模型选型</div>
          <div className="card-sub">
            按本机显存判断"能不能跑"，按科目判断"该用哪个" —— 不看排行榜参数量
          </div>
        </div>
        <button className="btn ghost" onClick={load}><RefreshCw size={14} /> 重新探测</button>
      </div>

      <div className="card-body">
        {/* ---- 硬件画像 ---- */}
        <div className="mp-hw">
          <div className="mp-hw-main">
            <span className="mp-hw-gpu">{hw.gpu_name || '未检测到独立显卡'}</span>
            <span className="mp-hw-tier">{tierLabel}</span>
          </div>
          <div className="mp-hw-stats">
            <div><span className="mp-hw-k">显存</span><span className="mp-hw-v">{hw.vram_gb || 0} GB</span></div>
            <div><span className="mp-hw-k">内存</span><span className="mp-hw-v">{hw.ram_gb || '—'} GB</span></div>
            <div>
              <span className="mp-hw-k">已装模型</span>
              <span className="mp-hw-v">{rep.installed_models.length || 0} 个</span>
            </div>
          </div>
          {!hw.cuda_available && (
            <div className="mp-warn">
              <Warning size={14} /> 未检测到可用 CUDA 环境。本地模型无法加速，
              建议先装 Ollama，或直接使用云端 API。
            </div>
          )}
        </div>

        {/* ---- Tab ---- */}
        <div className="mp-tabs">
          {[
            ['subject', '分科建议'],
            ['local', `本地模型 (${groups.local.length})`],
            ['cloud', `云端模型 (${groups.cloud.length})`],
          ].map(([k, label]) => (
            <button key={k} className={`chip ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>
              {label}
            </button>
          ))}
        </div>

        {/* ---- 分科建议 ---- */}
        {tab === 'subject' && (
          <div className="mp-subject">
            {rep.subject_plan.map((s) => {
              const top = s.recommendations[0]
              const alt = s.recommendations.slice(1)
              return (
                <div className="mp-subject-row" key={s.subject}>
                  <div className="mp-subject-name">
                    {s.subject}
                    <span className="mp-task">{s.task_desc}</span>
                  </div>
                  <div className="mp-subject-pick">
                    {top ? (
                      <>
                        <span className="mp-pick-name">{top.name}</span>
                        <span className={`mp-fit ${top.fit.level}`}>{top.fit.label}</span>
                        {top.subject_score > 0 && (
                          <span className="mp-score" title="该模型对本学科的强项评分">
                            强项 {top.subject_score}/5
                          </span>
                        )}
                      </>
                    ) : <span className="mp-none">暂无推荐</span>}
                  </div>
                  {alt.length > 0 && (
                    <div className="mp-subject-alt">
                      备选：{alt.map((a) => `${a.name}（${a.fit.label}）`).join(' · ')}
                    </div>
                  )}
                </div>
              )
            })}

            <div className="mp-batch">
              <div className="mp-batch-title">批量任务建议（文档处理 / OCR 纠错）</div>
              {rep.batch_plan.map((b) => (
                <div className="mp-batch-row" key={b.task}>
                  <span className="mp-batch-k">{b.task_desc}</span>
                  <span className="mp-batch-v">
                    {b.recommendations[0]?.name || '暂无'} —
                    批量场景优先速度，选小模型更划算
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ---- 模型列表 ---- */}
        {tab !== 'subject' && (
          <div className="mp-list">
            {groups[tab].map((m) => {
              const pullCmd = m.ollama_name ? `ollama pull ${m.ollama_name}` : ''
              return (
                <div className={`mp-model ${m.installed ? 'installed' : ''}`} key={m.key}>
                  <div className="mp-model-head">
                    <span className="mp-model-name">{m.name}</span>
                    <span className="mp-family">{m.family}</span>
                    {m.installed
                      ? <span className="mp-badge ok"><CheckCircle size={12} /> 已安装</span>
                      : m.local && <span className="mp-badge">{m.fit.label}</span>}
                    {!m.local && <span className="mp-badge cloud">云端 API</span>}
                  </div>

                  <div className="mp-model-meta">
                    {m.local && <span>{m.params_b}B</span>}
                    {m.local && <span>权重 ≈ {m.weights_gb}GB</span>}
                    {m.local && <span>总需求 ≈ {m.required_gb}GB</span>}
                    <span>上下文 {m.context_k}K</span>
                    <span title="中文能力">中文 {'★'.repeat(m.chinese)}{'☆'.repeat(5 - m.chinese)}</span>
                    <span title="推理/数学">推理 {'★'.repeat(m.reasoning)}{'☆'.repeat(5 - m.reasoning)}</span>
                    {m.local && <span title="相对速度">速度 {'★'.repeat(m.speed)}{'☆'.repeat(5 - m.speed)}</span>}
                  </div>

                  {m.strengths_cn && m.strengths_cn.length > 0 && (
                    <div className="mp-model-strengths">
                      {Object.entries(m.strengths_cn).map(([subj, score]) => (
                        <span className="tag" key={subj} title={`强项评分 ${score}/5`}>
                          {subj} {score}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="mp-model-note">{m.note}</div>

                  {m.local && m.fit.level !== 'too_big' && !m.installed && pullCmd && (
                    <div className="mp-model-cmd">
                      <code>{pullCmd}</code>
                      <button className="btn-xs" onClick={() => copy(pullCmd)}>
                        {copied === pullCmd ? '已复制' : '复制'}
                      </button>
                    </div>
                  )}
                  {m.local && m.fit.level === 'too_big' && (
                    <div className="mp-model-blocked">
                      <Warning size={13} /> {m.fit.detail}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {copied === 'FAIL' && <div className="mp-copied-fail">复制失败，请手动输入命令</div>}

        {/* ---- 说明 ---- */}
        <details className="mp-help">
          <summary>显存是怎么估算的？</summary>
          <ul>
            <li>权重 = 参数量(B) × 量化字节数（Q4_K_M ≈ 0.58 GB/B，Q8 ≈ 1.07）</li>
            <li>总需求 = 权重 + KV cache + 运行时开销（估算偏保守）</li>
            <li>可用显存 = 显卡显存 − 系统预留（8GB 卡按 0.8GB 预留）</li>
            <li>需求 ≤ 可用 × 0.85 → 完美适配；≤ 可用 → 可以运行；再高 → 勉强/不足</li>
            <li>
              判定依据是 <b>显存</b>，不是排行榜分数 ——
              云端 700B+ 的模型在这台机器上永远"显存不足"，列出来只为对照。
            </li>
          </ul>
        </details>
      </div>
    </section>
  )
}
