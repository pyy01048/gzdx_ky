import React, { useEffect, useState } from 'react'
import { kbApi } from '../api/client'
import { Warning, CheckCircle, RefreshCw } from '../components/Icon'

/**
 * 知识库健康面板：如实显示缺口，并提供一键修复。
 *
 * 「自主本地知识库建立」的可观测入口 ——
 * 不再需要去命令行跑脚本才知道知识库缺什么。
 */
export default function KbHealthPanel() {
  const [rep, setRep] = useState(null)
  const [status, setStatus] = useState('loading')
  const [healing, setHealing] = useState(false)
  const [healMsg, setHealMsg] = useState('')
  const [expanded, setExpanded] = useState(false)

  const load = async () => {
    try {
      const d = await kbApi.health()
      setRep(d)
      setStatus('ok')
      return d
    } catch {
      setStatus('error')
      return null
    }
  }

  useEffect(() => { load() }, [])

  /* 修复是后台任务（OCR 慢），轮询进度 */
  const pollHeal = async () => {
    for (let i = 0; i < 300; i++) {
      await new Promise((r) => setTimeout(r, 3000))
      try {
        const st = await kbApi.healStatus()
        if (st.stage) setHealMsg(`${st.stage}${st.detail ? ' · ' + st.detail : ''}`)
        if (!st.running) {
          setHealing(false)
          if (st.error) setHealMsg(`修复失败：${st.error}`)
          else setHealMsg('修复完成')
          await load()
          setTimeout(() => setHealMsg(''), 6000)
          return
        }
      } catch {
        /* 轮询失败继续重试 */
      }
    }
    setHealing(false)
    setHealMsg('修复超时，请稍后刷新查看结果')
  }

  const heal = async () => {
    setHealing(true)
    setHealMsg('正在启动修复…')
    try {
      const r = await kbApi.heal({ use_ocr: true })
      setHealMsg(r.message || '修复已启动')
      pollHeal()
    } catch (e) {
      setHealing(false)
      setHealMsg(`启动失败：${e.message}`)
    }
  }

  if (status === 'loading') {
    return <div className="card"><div className="card-body"><div className="loading-inline">知识库体检中…</div></div></div>
  }
  if (status === 'error' || !rep) {
    return (
      <div className="card">
        <div className="card-body">
          <div className="empty-hint">知识库体检失败，请确认后端已启动。</div>
          <button className="btn ghost" onClick={load}>重试</button>
        </div>
      </div>
    )
  }

  const d = rep.documents
  const c = rep.chunks
  const errors = rep.issues.filter((i) => i.level === 'error')
  const warns = rep.issues.filter((i) => i.level === 'warn')
  const infos = rep.issues.filter((i) => i.level === 'info')
  const fixable = rep.issues.filter((i) => i.auto).length

  return (
    <div className={`card kb-health ${rep.healthy ? 'ok' : 'has-issue'}`}>
      <div className="card-head">
        <div>
          <div className="card-title">
            {rep.healthy
              ? <><CheckCircle size={16} /> 知识库状态良好</>
              : <><Warning size={16} /> 知识库有 {errors.length + warns.length} 项待处理</>}
          </div>
          <div className="card-sub">
            文档 {d.total} 篇（已入库）· 分块 {c.total} · 已向量化 {c.with_embedding ?? '—'}
            {c.missing_embedding ? `（缺 ${c.missing_embedding}）` : ''}
          </div>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={load} disabled={healing}>
            <RefreshCw size={14} /> 重新体检
          </button>
          {fixable > 0 && (
            <button className="btn primary" onClick={heal} disabled={healing}>
              {healing ? '修复中…' : `一键修复 ${fixable} 项`}
            </button>
          )}
          <button className="btn ghost" onClick={() => setExpanded((v) => !v)}>
            {expanded ? '收起' : '看流程'}
          </button>
        </div>
      </div>

      <div className="card-body">
        {healMsg && <div className="kb-heal-msg">{healMsg}</div>}

        {/* 缺口清单 */}
        {rep.issues.length > 0 ? (
          <div className="kb-issue-list">
            {[...errors, ...warns, ...infos].map((it) => (
              <div className={`kb-issue ${it.level}`} key={it.key}>
                <span className="kb-issue-dot" />
                <div className="kb-issue-main">
                  <div className="kb-issue-title">
                    {it.title}
                    {it.auto && <span className="tag tag-new">可自动修复</span>}
                  </div>
                  <div className="kb-issue-impact">{it.impact}</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-hint"><CheckCircle size={16} /> 未发现缺口，知识库健康</div>
        )}

        {/* 数据明细 */}
        <div className="kb-health-grid">
          <div><span className="kb-h-label">状态分布</span>
            <span className="kb-h-val">{Object.entries(d.by_status || {}).map(([k, v]) => `${k} ${v}`).join(' · ')}</span>
          </div>
          <div><span className="kb-h-label">正文为空</span>
            <span className={`kb-h-val ${d.empty_content ? 'bad' : ''}`}>{d.empty_content} 篇</span>
          </div>
          <div><span className="kb-h-label">扫描件 OCR</span>
            <span className="kb-h-val">{d.ocr_used} 篇</span>
          </div>
          <div><span className="kb-h-label">缺资料层级</span>
            <span className={`kb-h-val ${d.missing_structure_level ? 'bad' : ''}`}>{d.missing_structure_level} 篇</span>
          </div>
        </div>

        {/* 建立流程说明 */}
        {expanded && (
          <div className="kb-flow">
            <div className="kb-flow-title">知识库建立链路</div>
            <ol>
              <li><b>扫描入库</b> — 目录递归扫描 PDF/Word/PPT/TXT/MD</li>
              <li><b>解析正文</b> — pypdf / pdfplumber 提取文本层</li>
              <li><b>扫描件 OCR</b> — 无文本层则逐页渲染走本地 RapidOCR</li>
              <li><b>分块</b> — 按段落/句子切分，块间带重叠</li>
              <li><b>全文索引</b> — jieba 分词写入 FTS5（BM25）</li>
              <li><b>向量索引</b> — bge-small-zh-v1.5 本地嵌入</li>
              <li><b>结构化</b> — 识别章节树，生成「章节→知识点→题型」</li>
              <li><b>元信息标记</b> — 资料层级（原始/加工/索引）+ 扫描件标记</li>
            </ol>
            <div className="kb-flow-entry">
              四个入口：目录批量导入 · 单文件上传 · 百度网盘下载入库 · 一键修复缺口
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
