import React, { useState, useEffect, useCallback } from 'react'
import { Modal, toast } from './UI'
import { PRESETS, providerPreset } from '../utils/api'
import { aiApi } from '../api/client'

/* ============================================================
   AI 服务管理（T1 重构：后端为唯一真相源）
   - 服务商 CRUD 直接读写数据库 ai_providers（后端网关立即可用）
   - 连通性测试走后端服务端（无浏览器 CORS 限制）
   - 路由模式热切换：自动互备 / 仅本地 / 仅云端
   旧版（localStorage 存 Key、浏览器直连）已废弃：那种配置后端网关
   根本看不到，且受 CORS 限制。
   ============================================================ */

export default function AiServiceManager() {
  const [providers, setProviders] = useState([])
  const [routing, setRouting] = useState(null) // {mode, options:[{mode,label}]}
  const [loadErr, setLoadErr] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [editingId, setEditingId] = useState(null) // null = 新增
  const [draft, setDraft] = useState({ key: 'deepseek', name: 'DeepSeek', baseUrl: PRESETS[0].baseUrl, model: PRESETS[0].model, apiKey: '' })
  const [testBusyId, setTestBusyId] = useState(null)
  const [testResults, setTestResults] = useState({}) // {id: {ok, latency, preview, error}}

  const load = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([
        aiApi.providers(),
        aiApi.getRouting().catch(() => null),
      ])
      setProviders(p || [])
      setRouting(r)
      setLoadErr(false)
    } catch {
      setLoadErr(true)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const openAdd = () => {
    setEditingId(null)
    setDraft({ key: 'deepseek', name: 'DeepSeek', baseUrl: PRESETS[0].baseUrl, model: PRESETS[0].model, apiKey: '' })
    setShowEdit(true)
  }

  const openEdit = (p) => {
    // provider_type 回映射到预设 key（ollama 等本地类型无预设，归 custom）
    const key = PRESETS.some((x) => x.key === p.provider_type) ? p.provider_type : 'custom'
    setEditingId(p.id)
    setDraft({ key, name: p.name, baseUrl: p.base_url || '', model: p.model_name || '', apiKey: '' })
    setShowEdit(true)
  }

  const onPreset = (key) => {
    const preset = providerPreset(key)
    setDraft({ ...draft, key, name: preset.name, baseUrl: preset.baseUrl, model: preset.model })
  }

  const save = async () => {
    if (!draft.name.trim() || !draft.baseUrl.trim() || !draft.model.trim()) {
      return toast('请完整填写名称 / Base URL / 模型')
    }
    if (!editingId && !draft.apiKey.trim() && draft.key !== 'custom') {
      return toast('新增云端服务需要填写 API Key')
    }
    const body = {
      name: draft.name.trim(),
      provider_type: draft.key === 'custom' ? 'custom' : draft.key,
      base_url: draft.baseUrl.trim().replace(/\/+$/, ''),
      model_name: draft.model.trim(),
      is_enabled: true,
    }
    if (draft.apiKey.trim()) body.api_key = draft.apiKey.trim() // 编辑时留空 = 保持原 Key 不变
    try {
      if (editingId) {
        await aiApi.updateProvider(editingId, body)
        toast('服务已更新')
      } else {
        await aiApi.saveProvider(body)
        toast('服务已添加，后端 AI 网关立即可用')
      }
      setShowEdit(false)
      load()
    } catch (e) {
      toast(`保存失败：${e.message}`)
    }
  }

  const runTest = async (p) => {
    setTestBusyId(p.id)
    try {
      const r = await aiApi.testProvider(p.id)
      setTestResults((s) => ({
        ...s,
        [p.id]: r.success
          ? { ok: true, latency: r.response_time, preview: (r.preview || '').slice(0, 80), usage: r.usage }
          : { ok: false, error: r.error || '未知错误', latency: r.response_time },
      }))
      toast(r.success ? `测试成功 · ${r.response_time}s` : `测试失败：${(r.error || '').slice(0, 60)}`)
    } catch (e) {
      setTestResults((s) => ({ ...s, [p.id]: { ok: false, error: e.message } }))
      toast(`测试失败：${e.message}`)
    }
    setTestBusyId(null)
  }

  const onRouting = async (mode) => {
    try {
      await aiApi.setRouting(mode)
      toast('路由模式已切换，立即生效')
      load()
    } catch (e) {
      toast(`切换失败：${e.message}`)
    }
  }

  const cur = routing?.mode

  return (
    <div className="tile set-tile">
      <div className="set-head">
        <b>AI 服务管理</b>
        <span>服务商配置 · 一键测试 · 本地/云端路由 · 后端统一调用</span>
      </div>

      {/* T1：路由模式 */}
      {routing && (
        <div style={{ marginBottom: 14, padding: '12px 14px', border: '1px solid var(--line)', borderRadius: 10, background: 'var(--surface-2)' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
            AI 路由模式
            <span style={{ fontWeight: 400, color: 'var(--ink-3)', marginLeft: 8 }}>
              控制答疑/组卷/解析等所有 AI 调用走本地 Ollama 还是云端 API，切换立即生效
            </span>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {routing.options.map((o) => (
              <button key={o.mode}
                className={`mini-btn ${cur === o.mode ? '' : ''}`}
                style={{
                  padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
                  border: cur === o.mode ? '1.5px solid var(--accent)' : '1px solid var(--line)',
                  background: cur === o.mode ? 'var(--accent)' : 'transparent',
                  color: cur === o.mode ? 'var(--surface)' : 'var(--ink-2)',
                  fontSize: 12.5,
                }}
                title={o.label}
                onClick={() => onRouting(o.mode)}>
                {o.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {loadErr && (
        <p style={{ fontSize: 13, color: 'var(--red, #c0392b)' }}>
          后端服务不可达，AI 配置读取失败。请确认后端已启动。
          <button className="mini-btn" style={{ marginLeft: 8 }} onClick={load}>重试</button>
        </p>
      )}

      {/* 服务列表 */}
      {providers.length === 0 && !loadErr && (
        <p style={{ fontSize: 13, color: 'var(--ink-3)' }}>尚未配置任何云端 AI 服务。本地 Ollama 模型无需在此配置，开箱即用。</p>
      )}
      <div className="ai-prov-list">
        {providers.map((p) => {
          const t = testResults[p.id]
          return (
            <div key={p.id} className={`ai-prov ${p.is_default ? 'is-default' : ''}`}>
              <div className="ai-prov-head">
                <span className="ai-prov-name">
                  {p.name}
                  {p.is_default && <em className="badge-dflt">默认</em>}
                  {!p.is_enabled && <em className="badge-off">停用</em>}
                  {/* 云端服务未配 Key 时显式提醒，避免"配了却调不通" */}
                  {p.provider_type !== 'ollama' && !p.has_api_key && <em className="badge-off">未配Key</em>}
                </span>
                <span className="ai-prov-model">{p.model_name}</span>
              </div>
              <div className="ai-prov-url">{p.base_url}</div>
              {t && (
                <div className={`ai-test-result ${t.ok ? 'ok' : 'fail'}`}>
                  {t.ok
                    ? `✓ 连通正常 · ${t.latency}s · 回复：${t.preview}`
                    : `✗ ${t.error}`}
                </div>
              )}
              <div className="ai-prov-actions">
                {!p.is_default && (
                  <button className="mini-btn" onClick={async () => { try { await aiApi.updateProvider(p.id, { is_default: true }); toast(`已设为默认：${p.name}`); load() } catch (e) { toast(e.message) } }}>设为默认</button>
                )}
                <button className="mini-btn" onClick={async () => { try { await aiApi.updateProvider(p.id, { is_enabled: !p.is_enabled }); load() } catch (e) { toast(e.message) } }}>
                  {p.is_enabled ? '停用' : '启用'}
                </button>
                <button className="mini-btn" onClick={() => openEdit(p)}>编辑</button>
                <button className="mini-btn" style={{ color: 'var(--green)' }} disabled={testBusyId === p.id} onClick={() => runTest(p)}>
                  {testBusyId === p.id ? '测试中…' : '测试接口'}
                </button>
                <button className="mini-btn danger" onClick={async () => { try { await aiApi.removeProvider(p.id); toast('已删除该服务'); load() } catch (e) { toast(e.message) } }}>删除</button>
              </div>
            </div>
          )
        })}
      </div>

      <div className="set-form-actions">
        <button className="btn primary" onClick={openAdd}>+ 添加云端 AI 服务</button>
      </div>
      <p style={{ fontSize: 12.5, color: 'var(--ink-3)', marginTop: 10, lineHeight: 1.7 }}>
        支持 DeepSeek、豆包(火山方舟)、通义千问、智谱、OpenAI 等 OpenAI 兼容接口。
        配置保存在本机数据库并由后端统一调用（无跨域问题）；「测试接口」从服务端发起真实对话验证。
        本地 Ollama 模型自动可用，无需在此添加。Key 不回传前端，编辑时留空即保持不变。
      </p>

      {/* 编辑/新增弹窗 */}
      <Modal open={showEdit} title={editingId ? '编辑 AI 服务' : '添加 AI 服务'} onClose={() => setShowEdit(false)}
        footer={<React.Fragment><button className="btn ghost" onClick={() => setShowEdit(false)}>取消</button><button className="btn primary" onClick={save}>保存</button></React.Fragment>}>
        <label>服务商预设
          <select className="input" value={draft.key} onChange={(e) => onPreset(e.target.value)}>
            {PRESETS.map((pr) => <option key={pr.key} value={pr.key}>{pr.name}{pr.vision ? '（支持视觉）' : ''}</option>)}
          </select>
        </label>
        <label>显示名称
          <input className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="如：我的 DeepSeek" />
        </label>
        <label>Base URL
          <input className="input" value={draft.baseUrl} onChange={(e) => setDraft({ ...draft, baseUrl: e.target.value })} placeholder="https://api.deepseek.com" />
        </label>
        <label>模型名称
          <input className="input" value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} placeholder="deepseek-chat" />
        </label>
        <label>API Key {editingId && <span style={{ color: 'var(--ink-3)', fontSize: 12 }}>（留空 = 保持原 Key 不变）</span>}
          <input className="input" type="password" value={draft.apiKey} onChange={(e) => setDraft({ ...draft, apiKey: e.target.value })} placeholder="sk-…" />
        </label>
      </Modal>
    </div>
  )
}
