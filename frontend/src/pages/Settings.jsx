import React, { useEffect, useRef, useState } from 'react'
import useStore from '../store/useStore'
import { Modal, Empty, toast } from '../components/UI'
import { todayStr } from '../utils/date'
import { goalsApi } from '../api/client'
import { kaoyanApi } from '../api/kaoyanApi'
import AiServiceManager from '../components/AiServiceManager'
import LanAccessCard from '../components/LanAccessCard'
import ModelSelectPanel from '../components/ModelSelectPanel'
import SubjectSettings from '../components/SubjectSettings'
import { getStatus as getPanStatus, getStoredPan, clearPan } from '../utils/pan'
import { aiApi, dashboardApi } from '../api/client'

/* 应用真实接入的快捷键（源码可证：Layout / UI.Modal / Tasks） */
const SHORTCUTS = [
  { keys: ['⌘ / Ctrl', 'K'], desc: '打开全局命令面板（检索页面 / 功能）', scope: '全局' },
  { keys: ['Esc'], desc: '关闭当前弹窗 / 面板（Modal 组件统一支持）', scope: '全局' },
  { keys: ['←', '→'], desc: '任务页：切换 日 / 周 / 月 视图', scope: '任务' },
  { keys: ['Enter'], desc: '输入框：发送消息 / 提交答案 / 确认内联添加', scope: '多页' },
  { keys: ['Esc'], desc: '任务页：取消内联添加', scope: '任务' },
]

export default function Settings() {
  const { settings, updateSettings, resetAll, tasks, notebook, pan, words, cards } = useStore()
  const [form, setForm] = useState({ ...settings })
  const [showReset, setShowReset] = useState(false)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const fileRef = useRef(null)

  /* ---- 后端聚合数据（今日学习时长等）---- */
  const [live, setLive] = useState(null)
  const [liveLoading, setLiveLoading] = useState(true)   /* 批次2-2：实时数据加载态 */
  const [liveError, setLiveError] = useState(false)       /* 批次2-2：加载失败时渲染 Empty */
  useEffect(() => {
    let alive = true
    setLiveLoading(true); setLiveError(false)
    dashboardApi.get()
      .then((d) => { if (alive) setLive(d) })
      .catch(() => { if (alive) setLiveError(true) })
      .finally(() => { if (alive) setLiveLoading(false) })
    return () => { alive = false }
  }, [])

  /* ---- 百度网盘状态 ---- */
  const [panSt, setPanSt] = useState({ configured: false })
  const [panLoading, setPanLoading] = useState(true)   /* 批次2-2：网盘状态检测加载态 */
  const [panTok, setPanTok] = useState(getStoredPan())

  /* ---- 本地模型（Ollama）状态 ---- */
  const [localModel, setLocalModel] = useState({ checking: true, available: false, models: [] })
  const [localTesting, setLocalTesting] = useState(false)
  const [localTestResult, setLocalTestResult] = useState(null)

  const checkLocalModel = async () => {
    try {
      const status = await aiApi.localStatus()
      const models = await aiApi.localModels()
      setLocalModel({
        checking: false,
        available: status.available,
        models: models.models || [],
      })
    } catch (e) {
      setLocalModel({ checking: false, available: false, models: [] })
    }
  }

  const testLocalModel = async () => {
    setLocalTesting(true)
    setLocalTestResult(null)
    try {
      const result = await aiApi.localTest('qwen3.5:4b', '你好，请用一句话介绍你自己。')
      setLocalTestResult(result)
      if (result.success) {
        toast('本地模型测试成功')
      } else {
        toast('本地模型测试失败：' + (result.error || '未知错误'))
      }
    } catch (e) {
      toast('本地模型测试失败：' + e.message)
    } finally {
      setLocalTesting(false)
    }
  }

  useEffect(() => {
    checkLocalModel()
  }, [])

  useEffect(() => {
    // 批次1-2：CodeBuddy Agent 已下线（无后端实现），不再探测 /api/agent/*（原每开一次设置页白发 2 次 404）。
    // 仅保留网盘状态探测。
    setPanLoading(true)
    getPanStatus()
      .then((st) => setPanSt(st))
      .catch(() => toast('网盘服务状态获取失败，请检查后端是否启动'))
      .finally(() => setPanLoading(false))
  }, [])

  const setTheme = (t) => {
    updateSettings({ theme: t })
    setForm({ ...form, theme: t })
  }

  // T2：目标院校可更换——从院校库拉可选名单（datalist：可搜索可选，也可手输）
  const [schoolOptions, setSchoolOptions] = useState([])
  useEffect(() => {
    kaoyanApi.schools({ page: 1, page_size: 500 })
      .then((d) => {
        const list = (d?.items || []).map((s) => s.name).filter(Boolean)
        setSchoolOptions([...new Set(list)])
      })
      .catch(() => { /* 后端不可达时退化为手输，不打断设置页 */ })
  }, [])

  const saveSettings = async () => {
    updateSettings({ ...form, examDate: form.examDate || '2027-12-25' })
    // 同步写后端 goals 表：sync 加载器会用后端 goal 覆盖本地，
    // 只写 localStorage 会被旧值顶回去（此前"改了不生效"的根因）
    try {
      await goalsApi.update({
        university: form.school || null,
        major: form.major || null,
        exam_date: form.examDate || null,
        total_score_target: Number(form.targetScore) || null,
      })
      toast('设置已保存（本地 + 后端目标档案）')
    } catch {
      toast('已保存到本地；同步后端目标档案失败（后端未启动？）')
    }
  }

  const exportData = () => {
    const data = {
      exportedAt: new Date().toISOString(),
      settings, tasks, notebook, pan
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `考研档案备份-${todayStr()}.json`
    a.click()
    URL.revokeObjectURL(url)
    toast('已导出备份文件')
  }

  const importData = (e) => {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result)
        if (data.settings) updateSettings(data.settings)
        if (data.tasks) useStore.setState({ tasks: data.tasks })
        if (data.notebook) useStore.setState({ notebook: data.notebook })
        if (data.pan) useStore.setState({ pan: data.pan })
        if (data.words) useStore.setState({ words: data.words })
        if (data.cards) useStore.setState({ cards: data.cards })
        toast('备份导入成功')
      } catch {
        toast('文件格式无效，导入失败')
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  const doReset = () => {
    resetAll()
    setForm({ ...useStore.getState().settings })
    setShowReset(false)
    toast('已恢复初始示例数据')
  }

  /* ---- 数据可视化：从 useStore 实时读取 ---- */
  const totalTasks = (tasks || []).length
  const pendingTasks = (tasks || []).filter((t) => !t.done).length
  const totalCards = (cards || []).length
  const totalWords = (words || []).length
  const totalNotes = (notebook || []).length
  // 今日学习时长改从后端聚合读取（番茄钟已移除）
  const focusMinutes = live?.stats?.today_duration || 0

  const tiles = [
    { ico: '📋', bg: 'var(--accent-soft)', fg: 'var(--accent)', val: totalTasks, label: '任务总数', delta: `待办 ${pendingTasks}` },
    { ico: '🗂', bg: 'rgba(56,189,248,.12)', fg: '#38bdf8', val: totalCards, label: '记忆卡片', delta: 'SM-2 复习' },
    { ico: '🔤', bg: 'rgba(52,211,153,.12)', fg: '#34d399', val: totalWords, label: '单词本', delta: '生词积累' },
    { ico: '📝', bg: 'rgba(251,191,36,.14)', fg: '#fbbf24', val: totalNotes, label: '错题本', delta: '七刷法' },
    { ico: '⏱', bg: 'rgba(167,139,250,.14)', fg: '#a78bfa', val: focusMinutes, label: '今日学习', delta: '分钟' },
  ]

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">设置</h1>
          <p className="page-sub">备考目标 · AI 引擎 · 平台授权 · 外观 · 数据管理</p>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={() => setShowShortcuts(true)}>⌨ 快捷键</button>
        </div>
      </div>

      <div className="stack">
        {/* 学习数据一览（新功能②：数据可视化） */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title">学习数据一览</div>
              <div className="card-sub">实时读取本地档案，掌握复习资产与今日投入</div>
            </div>
            <span className="badge accent">本地实时</span>
          </div>
          <div className="grid-4">
            {tiles.map((t, i) => (
              <div className="stat-tile" key={i}>
                <div className="st-ico" style={{ background: t.bg, color: t.fg }}>{t.ico}</div>
                <div className="st-val">{t.val}</div>
                <div className="st-label">{t.label}</div>
                <div className="st-delta">{t.delta}</div>
              </div>
            ))}
          </div>
          {/* 批次2-2：后端实时数据加载失败时给出可见空状态，替代此前静默留 0 */}
          {liveError && (
            <div style={{ marginTop: 12 }}>
              <Empty icon={<span style={{ fontSize: 28 }}>📡</span>} title="实时学习数据获取失败" desc="后端未启动或网络异常；本地档案统计仍正常，启动后端后自动恢复今日时长等实时数据" />
            </div>
          )}
        </section>

        {/* 备考目标 */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title">备考目标</div>
              <div className="card-sub">用于仪表盘倒计时、AI 助手画像与规划建议</div>
            </div>
          </div>
          <div className="card-body">
            <div className="grid-2">
              <div className="field">
                <label>目标院校{schoolOptions.length ? <span style={{ fontWeight: 400, color: 'var(--ink-3)', fontSize: 12 }}>（可从院校库 {schoolOptions.length} 所中选择，也可手动输入）</span> : null}</label>
                <input className="input" list="kaoyan-school-options" value={form.school} onChange={(e) => setForm({ ...form, school: e.target.value })} placeholder="如：贵州大学" />
                <datalist id="kaoyan-school-options">
                  {schoolOptions.map((n) => <option key={n} value={n} />)}
                </datalist>
              </div>
              <div className="field">
                <label>报考专业</label>
                <input className="input" value={form.major} onChange={(e) => setForm({ ...form, major: e.target.value })} placeholder="如：电子信息（0854）" />
              </div>
              <div className="field">
                <label>考试日期</label>
                <input className="input" type="date" value={form.examDate} onChange={(e) => setForm({ ...form, examDate: e.target.value })} />
              </div>
              <div className="field">
                <label>目标分数</label>
                <input className="input" type="number" value={form.targetScore} onChange={(e) => setForm({ ...form, targetScore: Number(e.target.value) })} />
              </div>
            </div>
            <div className="card-foot" style={{ justifyContent: 'flex-start' }}>
              <button className="btn primary" onClick={saveSettings}>保存设置</button>
            </div>
          </div>
        </section>

        {/* CodeBuddy Agent 引擎（批次1-2：当前版本未包含后端 Agent 插件，仅作说明，不再发起 /api/agent/* 请求） */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title">CodeBuddy Agent 引擎</div>
              <div className="card-sub">需后端额外安装 Agent 插件，当前版本未包含。基础 AI 对话请使用「AI 助手」页。</div>
            </div>
            <span className="badge warning">未包含</span>
          </div>
        </section>

        {/* 百度网盘授权 */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title">百度网盘授权</div>
              <div className="card-sub">在「网盘联动」页可扫码 / 授权后浏览同步网盘资料</div>
            </div>
            {panLoading ? <span className="badge info">检测中…</span> : panSt.configured ? <span className="badge success">已配置</span> : <span className="badge warning">未配置</span>}
          </div>
          <div className="card-body">
            <div className="row wrap">
              <span style={{ fontSize: 13, color: 'var(--ink-2)' }}>
                服务端凭证：{panSt.configured ? `已配置 ✓（AppID ${panSt.appId}）` : '未配置'}
              </span>
              {panTok && panTok.access_token ? (
                <button className="btn danger" onClick={() => { clearPan(); setPanTok(null); toast('已清除本机网盘授权') }}>清除授权</button>
              ) : (
                <span style={{ fontSize: 12.5, color: 'var(--ink-3)' }}>本机未授权，可前往「网盘联动」页完成 OAuth 绑定</span>
              )}
            </div>
            {!panSt.configured && (
              <p style={{ fontSize: 12.5, color: 'var(--ink-3)', marginTop: 8, lineHeight: 1.8 }}>
                配置方法：在 <code>backend-main-fastapi/.env</code> 中填写百度开放平台个人应用凭证（<code>BAIDU_NETDISK_APP_ID</code> / <code>BAIDU_NETDISK_APP_KEY</code> / <code>BAIDU_NETDISK_SECRET_KEY</code>），并重启后端。
              </p>
            )}
          </div>
        </section>

        {/* 外观主题（V2：segmented 浅 / 深 / 跟随系统） */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title">外观主题</div>
              <div className="card-sub">明色「纸上备考」与暗色「深夜自习」，或跟随系统自动切换</div>
            </div>
            <span className="badge accent">
              {settings.theme === 'dark' ? '深夜自习' : settings.theme === 'system' ? '跟随系统' : '纸上备考'}
            </span>
          </div>
          <div className="card-body">
            <div className="segmented">
              <button className={`seg ${settings.theme === 'light' ? 'active' : ''}`} onClick={() => setTheme('light')}>☀ 浅色</button>
              <button className={`seg ${settings.theme === 'dark' ? 'active' : ''}`} onClick={() => setTheme('dark')}>☾ 深色</button>
              <button className={`seg ${settings.theme === 'system' ? 'active' : ''}`} onClick={() => setTheme('system')}>🖥 跟随系统</button>
            </div>
            <p style={{ fontSize: 12.5, color: 'var(--ink-3)', marginTop: 4 }}>
              选择「跟随系统」后，主题将随操作系统的亮 / 暗模式实时变化。
            </p>
          </div>
        </section>

        {/* 本地模型（Ollama） */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title">本地模型（Ollama）</div>
              <div className="card-sub">离线 AI 引擎 · 数据不出网 · 简单问题本地秒回，复杂问题自动走在线 API</div>
            </div>
            {localModel.checking
              ? <span className="badge info">检测中</span>
              : localModel.available ? <span className="badge success">已连接</span> : <span className="badge danger">未启动</span>}
          </div>
          <div className="card-body">
            <div className="row wrap">
              <span style={{ fontSize: 13, color: 'var(--ink-2)' }}>
                服务状态：{localModel.checking ? '检测中…' : localModel.available ? '已连接 ✓' : '未启动 / 未安装'}
              </span>
              <button className="btn ghost" onClick={checkLocalModel} disabled={localModel.checking}>
                {localModel.checking ? '检测中…' : '重新检测'}
              </button>
              <button className="btn ghost" onClick={testLocalModel} disabled={localTesting || !localModel.available}>
                {localTesting ? '测试中…' : '测试模型'}
              </button>
            </div>
            {localModel.available && localModel.models.length > 0 && (
              <div className="row wrap" style={{ marginTop: 12, gap: 8 }}>
                <b style={{ fontSize: 13, color: 'var(--ink-2)', width: '100%' }}>已安装模型：</b>
                {localModel.models.map((m, i) => (
                  <span key={i} className="chip">{m.name} ({m.size_gb} GB)</span>
                ))}
              </div>
            )}
            {localTestResult && localTestResult.success && (
              <div style={{ marginTop: 12, padding: 12, background: 'var(--surface-2)', borderRadius: 'var(--r-sm)', fontSize: 13 }}>
                <b style={{ color: 'var(--green)' }}>测试成功 ✓</b>
                <div style={{ marginTop: 6, color: 'var(--ink-2)' }}>{localTestResult.response}</div>
                <div style={{ marginTop: 6, fontSize: 12, color: 'var(--ink-3)' }}>
                  模型：{localTestResult.model} · 生成 {localTestResult.eval_count} tokens · 耗时 {localTestResult.total_duration_ms} ms
                </div>
              </div>
            )}
            {!localModel.available && !localModel.checking && (
              <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--ink-3)', lineHeight: 1.7 }}>
                未检测到 Ollama 服务。请先安装 Ollama（<a href="https://ollama.com/download" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }}>下载地址</a>），
                然后运行 <code style={{ background: 'var(--surface-2)', padding: '1px 6px', borderRadius: 4 }}>ollama run qwen3.5:4b</code> 拉取轻量模型。
                本地模型可处理简单问题（定义、概念、单词等），复杂问题自动走在线 API。
              </div>
            )}
          </div>
        </section>

        {/* AI 服务管理（自定义 API，组件自带渲染） */}
        {/* 备考科目：决定统计口径与路由范围 */}
        <SubjectSettings />

        {/* 模型选型：硬件适配 + 分科路由建议 */}
        <ModelSelectPanel />

        <AiServiceManager />

        {/* 手机访问（局域网服务器） */}
        <LanAccessCard />

        {/* 数据管理 */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title">数据管理</div>
              <div className="card-sub">数据存储于本地浏览器（localStorage），可导出 JSON 备份，换设备时导入恢复</div>
            </div>
          </div>
          <div className="card-body">
            <div className="row wrap">
              <button className="btn ghost" onClick={exportData}>导出备份</button>
              <button className="btn ghost" onClick={() => fileRef.current?.click()}>导入备份</button>
              <button className="btn ghost" onClick={() => setShowShortcuts(true)}>⌨ 快捷键说明</button>
              <button className="btn danger" onClick={() => setShowReset(true)}>恢复初始数据</button>
              <input ref={fileRef} type="file" accept="application/json,.json" style={{ display: 'none' }} onChange={importData} />
            </div>
          </div>
        </section>

        {/* 关于 */}
        <section className="card">
          <div className="card-head">
            <div>
              <div className="card-title">关于本应用</div>
              <div className="card-sub">考研档案 · 综合考研全流程复习规划 Agent 应用</div>
            </div>
          </div>
          <div className="card-body">
            <p style={{ fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.85 }}>
              围绕 <strong>贵大 834 电子技术基础</strong>（数电 + 模电）+ 数二 / 英二 / 政治 收口，共八大模块：
              仪表盘（倒计时 / 今日任务 / 复习提醒）· 任务打卡（日周月视图 / AI 规划）·
              <strong>知识地图</strong>（章节 → 知识点 → 题型三级结构 + 复习进度追踪）·
              文档知识库（扫描版真题 OCR → 分块 → RAG 检索）· 刷题中心与错题本（错题自动挂靠考点）·
              AI 助手（本地 Ollama / DeepSeek 等云端 API 可切换）· 网盘联动（百度网盘 OAuth 直连）。
              <br />
              技术栈：Vite + React + Zustand + React Router + FastAPI + SQLite。响应式设计，支持电脑 / 平板 / 手机三端，数据全部本地存储不出网。
            </p>
          </div>
        </section>
      </div>

      {/* 恢复初始数据确认 */}
      <Modal open={showReset} title="恢复初始数据" onClose={() => setShowReset(false)}
        footer={<React.Fragment><button className="btn ghost" onClick={() => setShowReset(false)}>取消</button><button className="btn danger" onClick={doReset}>确认恢复</button></React.Fragment>}>
        <p style={{ fontSize: 14, color: 'var(--ink-2)', lineHeight: 1.8 }}>
          此操作将<strong style={{ color: 'var(--red)' }}>清空当前所有数据</strong>（任务、错题、网盘记录），
          并恢复为初始示例数据，且不可撤销。
        </p>
        <p style={{ fontSize: 12.5, color: 'var(--ink-3)' }}>建议先执行「导出备份」再操作。</p>
      </Modal>

      {/* 快捷键面板（新功能①） */}
      <Modal open={showShortcuts} title="键盘快捷键" onClose={() => setShowShortcuts(false)}
        footer={<button className="btn primary" onClick={() => setShowShortcuts(false)}>知道了</button>}>
        <p style={{ fontSize: 12.5, color: 'var(--ink-3)', marginBottom: 12 }}>
          以下为应用中已真实接入的快捷键，部分仅在对应页面生效。
        </p>
        <div className="list">
          {SHORTCUTS.map((s, i) => (
            <div className="list-row" key={i}>
              <div className="lr-ico">
                {s.keys.map((k, j) => (
                  <React.Fragment key={k}>
                    <kbd style={{ fontFamily: 'var(--font-mono)', fontSize: 12, padding: '2px 8px', border: '1px solid var(--line)', borderRadius: 6, background: 'var(--surface-2)', color: 'var(--ink)', whiteSpace: 'nowrap' }}>{k}</kbd>
                    {j < s.keys.length - 1 && <span style={{ color: 'var(--ink-3)', margin: '0 2px' }}>+</span>}
                  </React.Fragment>
                ))}
              </div>
              <div className="lr-main" style={{ flex: 1 }}>{s.desc}</div>
              <span className="badge info">{s.scope}</span>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  )
}
