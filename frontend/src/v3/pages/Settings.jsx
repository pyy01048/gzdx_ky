import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import useStore from '../../store/useStore'
import { todayStr } from '../../utils/date'
import {
  adminUsersApi, aiApi, dashboardApi, goalsApi, systemApi, taxonomyApi,
} from '../../api/client'
import { kaoyanApi } from '../../api/kaoyanApi'
import { PRESETS, providerPreset } from '../../utils/api'
import { useAuth } from '../../auth/AuthContext'
import { getStatus as getPanStatus, getStoredPan, clearPan } from '../../utils/pan'
import {
  DASH_SECTIONS, moveInOrder, resetUiLayout, toggleHidden, useUiLayout,
} from '../../hooks/useUiLayout'
import {
  Alert, AnimatedNumber, Avatar, Badge, Button, Card, CardHead, Chip, Dialog,
  Empty, Field, IconButton, Input, Progress, Segmented, Select, Skeleton, Switch,
  Textarea, Tile, toast, toastErr, toastOk, toastWarn, useConfirm,
} from '../ui'
import {
  Book, Brain, Calendar, CheckCircle, ChevronDown, ChevronUp, Clock, Cloud,
  Compass, Cpu, Database, Download, ExternalLink, FileText, HardDrive, KeyRound,
  Keyboard, Lock, LogOut, Moon, Plus, RefreshCw, Rocket, School, Search, Server,
  Shield, SlidersHorizontal, Sparkles, Sun, Target, Trash, Upload, User, Wand,
} from '../icons'
import '../styles/settings-v3.css'

const SETTINGS_TABS = [
  { id: 'overview', label: '目标与概览', icon: <Target size={15} /> },
  { id: 'ai', label: 'AI 与模型', icon: <Cpu size={15} /> },
  { id: 'appearance', label: '外观与数据', icon: <Sun size={15} /> },
  { id: 'account', label: '账号与安全', icon: <Shield size={15} /> },
]
const VALID_TABS = SETTINGS_TABS.map((t) => t.id)

const SHORTCUTS = [
  { keys: ['⌘ / Ctrl', 'K'], desc: '打开全局命令面板（检索页面 / 功能）', scope: '全局' },
  { keys: ['Esc'], desc: '关闭当前弹窗 / 面板（Dialog 组件统一支持）', scope: '全局' },
  { keys: ['←', '→'], desc: '任务页：切换 日 / 周 / 月 视图', scope: '任务' },
  { keys: ['Enter'], desc: '输入框：发送消息 / 提交答案 / 确认内联添加', scope: '多页' },
  { keys: ['Esc'], desc: '任务页：取消内联添加', scope: '任务' },
]

const IRRELEVANT_SUBJECTS = [
  '管理类联考综合', '经济类联考综合', '法律硕士专业基础', '教育学专业基础',
  '心理学专业基础', '西医综合', '中医综合', '其他', '网络补充',
]

const ROLE_LABEL = { admin: '管理员', user: '普通用户' }
const EMPTY_USER_FORM = { username: '', display_name: '', role: 'user', password: '' }
const fmtDateTime = (iso) => (iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '—')

/* 设置页内嵌「界面自定义」的静态清单。
   为避免把旧版 Dashboard / navConfig 的组件树（含旧图标与 CSS）拉进 v3，
   这里只镜像它们的可配置元数据，行为与旧设置页一致。 */
const NAV_MODULE_ITEMS = [
  { key: 'today', title: '今日' },
  { key: 'learn', title: '学习' },
  { key: 'practice', title: '练习' },
  { key: 'review', title: '复盘' },
  { key: 'school', title: '择校' },
]
const NAV_OTHER_ITEMS = [
  { to: '/assistant', label: 'AI 助手' },
  { to: '/settings', label: '设置' },
]

export default function Settings() {
  const settings = useStore((s) => s.settings)
  const updateSettings = useStore((s) => s.updateSettings)
  const resetAll = useStore((s) => s.resetAll)
  const tasks = useStore((s) => s.tasks)
  const notebook = useStore((s) => s.notebook)
  const pan = useStore((s) => s.pan)
  const words = useStore((s) => s.words)
  const cards = useStore((s) => s.cards)
  const { isAdmin } = useAuth()
  const allowTab = (id) => VALID_TABS.includes(id) && (isAdmin || id !== 'ai')

  const [form, setForm] = useState({ ...settings, examDate: settings.examDate || '' })
  const [showReset, setShowReset] = useState(false)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const [tab, setTab] = useState(() => {
    const t = new URLSearchParams(window.location.search).get('tab')
    return allowTab(t) ? t : 'overview'
  })
  const fileRef = useRef(null)

  useEffect(() => {
    const t = searchParams.get('tab')
    if (t && t !== tab && allowTab(t)) setTab(t)
    if (!isAdmin && tab === 'ai') setTab('overview')
  }, [searchParams, tab, isAdmin])

  const switchTab = (id) => {
    setTab(id)
    setSearchParams(id === 'overview' ? {} : { tab: id }, { replace: true })
  }

  useEffect(() => { window.scrollTo({ top: 0 }) }, [tab])

  /* ---- 届数 / 初试日期（后端 services/exam_calendar 是唯一权威） ---- */
  const [cal, setCal] = useState(null)
  const [calYear, setCalYear] = useState('')
  const [calSaving, setCalSaving] = useState(false)
  useEffect(() => {
    let alive = true
    goalsApi.examCalendar()
      .then((d) => {
        if (!alive) return
        setCal(d)
        setCalYear(String(d.exam_year || ''))
        if (d.exam_date) setForm((f) => ({ ...f, examDate: d.exam_date }))
      })
      .catch(() => { /* 后端不可达时保留本地设置，不阻塞页面 */ })
    return () => { alive = false }
  }, [])

  const applyExamYear = async (year) => {
    setCalYear(String(year))
    setCalSaving(true)
    try {
      const d = await goalsApi.updateExamCalendar({ exam_year: Number(year) })
      setCal(d)
      setForm((f) => ({ ...f, examDate: d.exam_date }))
      updateSettings({ examDate: d.exam_date })
      toast(`已切换到 ${d.exam_year} 届 · 初试 ${d.exam_date}${d.is_official ? '（教育部公布）' : '（预估）'}`)
      if (d.total_score_adjusted_from) {
        toast(`总分目标已按四科之和校正为 ${d.total_score_adjusted_from.new}`, 4000)
      }
    } catch (e) {
      toast(`切换失败：${e?.message || e}`)
    } finally {
      setCalSaving(false)
    }
  }

  /* ---- 后端聚合数据 ---- */
  const [live, setLive] = useState(null)
  const [liveLoading, setLiveLoading] = useState(true)
  const [liveError, setLiveError] = useState(false)
  useEffect(() => {
    let alive = true
    setLiveLoading(true)
    setLiveError(false)
    dashboardApi.get()
      .then((d) => { if (alive) setLive(d) })
      .catch(() => { if (alive) setLiveError(true) })
      .finally(() => { if (alive) setLiveLoading(false) })
    return () => { alive = false }
  }, [])

  /* ---- 百度网盘 ---- */
  const [panSt, setPanSt] = useState({ configured: false })
  const [panLoading, setPanLoading] = useState(true)
  const [panTok, setPanTok] = useState(getStoredPan())

  useEffect(() => {
    setPanLoading(true)
    getPanStatus()
      .then((st) => setPanSt(st))
      .catch(() => toast('网盘服务状态获取失败，请检查后端是否启动'))
      .finally(() => setPanLoading(false))
  }, [])

  /* ---- 本地模型（Ollama） ---- */
  const [localModel, setLocalModel] = useState({ checking: true, available: false, models: [] })
  const [localTesting, setLocalTesting] = useState(false)
  const [localTestResult, setLocalTestResult] = useState(null)

  const checkLocalModel = async () => {
    setLocalModel((m) => ({ ...m, checking: true }))
    try {
      const status = await aiApi.localStatus()
      const models = await aiApi.localModels()
      setLocalModel({ checking: false, available: status.available, models: models.models || [] })
    } catch {
      setLocalModel({ checking: false, available: false, models: [] })
    }
  }

  const testLocalModel = async () => {
    setLocalTesting(true)
    setLocalTestResult(null)
    try {
      const result = await aiApi.localTest('qwen3.5:4b', '你好，请用一句话介绍你自己。')
      setLocalTestResult(result)
      if (result.success) toastOk('本地模型测试成功')
      else toastErr('本地模型测试失败：' + (result.error || '未知错误'))
    } catch (e) {
      toastErr('本地模型测试失败：' + e.message)
    } finally {
      setLocalTesting(false)
    }
  }

  useEffect(() => { if (isAdmin) checkLocalModel() }, [isAdmin])

  const setTheme = (t) => {
    updateSettings({ theme: t })
    setForm((f) => ({ ...f, theme: t }))
  }

  /* ---- 目标院校候选（分页拉全，去重） ---- */
  const [schoolOptions, setSchoolOptions] = useState([])
  useEffect(() => {
    let alive = true
    const PAGE = 200
    const MAX_PAGES = 15
    ;(async () => {
      try {
        const first = await kaoyanApi.schools({ page: 1, page_size: PAGE })
        const firstItems = first?.items || []
        const total = Number(first?.total) || firstItems.length
        const pages = Math.min(MAX_PAGES, Math.max(1, Math.ceil(total / PAGE)))
        const all = [...firstItems]
        for (let p = 2; p <= pages; p++) {
          const d = await kaoyanApi.schools({ page: p, page_size: PAGE })
          all.push(...(d?.items || []))
        }
        if (!alive) return
        const list = all.map((s) => s.name).filter(Boolean)
        setSchoolOptions([...new Set(list)])
      } catch {
        /* 后端不可达时退化为手输 */
      }
    })()
    return () => { alive = false }
  }, [])

  const saveSettings = async () => {
    updateSettings({ ...form, examDate: form.examDate || null })
    try {
      await goalsApi.update({
        university: form.school || null,
        major: form.major || null,
        exam_date: form.examDate || null,
        total_score_target: Number(form.targetScore) || null,
      })
      toastOk('设置已保存（本地 + 后端目标档案）')
    } catch {
      toastWarn('已保存到本地；同步后端目标档案失败（后端未启动？）')
    }
  }

  const exportData = () => {
    const data = {
      exportedAt: new Date().toISOString(),
      settings, tasks, notebook, pan,
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `硕途备份-${todayStr()}.json`
    a.click()
    URL.revokeObjectURL(url)
    toastOk('已导出备份文件')
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
        toastOk('备份导入成功')
      } catch {
        toastErr('文件格式无效，导入失败')
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  const doReset = () => {
    resetAll()
    setForm({ ...useStore.getState().settings })
    setShowReset(false)
    toastOk('本地缓存已重置（服务器数据未删除，联网同步会重新拉回）')
  }

  const totalTasks = (tasks || []).length
  const pendingTasks = (tasks || []).filter((t) => !t.done).length
  const totalCards = (cards || []).length
  const totalWords = (words || []).length
  const totalNotes = (notebook || []).length
  const focusMinutes = live?.stats?.today_duration || 0

  const tiles = [
    { icon: Target, val: totalTasks, label: '任务总数', hint: `待办 ${pendingTasks}`, tone: 'primary' },
    { icon: Brain, val: totalCards, label: '记忆卡片', hint: 'SM-2 复习', tone: 'violet' },
    { icon: Book, val: totalWords, label: '单词本', hint: '生词积累', tone: 'success' },
    { icon: FileText, val: totalNotes, label: '错题本', hint: '七刷法', tone: 'warning' },
    { icon: Clock, val: focusMinutes, label: '今日学习', hint: '分钟', tone: 'info' },
  ]

  return (
    <div className="v3-stack v3-settings">
      <div className="v3-settings-head">
        <div className="v3-settings-head__aurora" aria-hidden="true" />
        <div className="v3-settings-head__inner">
          <div>
            <div className="v3-eyebrow"><Sparkles size={13} /> 偏好与配置</div>
            <h1 className="v3-settings-title">设置</h1>
            <p className="v3-settings-sub">
              备考目标{isAdmin ? ' · AI 引擎' : ''} · 外观与数据 · 账号安全
            </p>
          </div>
          <div className="v3-row">
            <Button variant="outline" icon={<Keyboard size={15} />} onClick={() => setShowShortcuts(true)}>
              快捷键
            </Button>
          </div>
        </div>
      </div>

      <div className="v3-settings-tabs">
        <Segmented
          options={SETTINGS_TABS.filter((t) => isAdmin || t.id !== 'ai')
            .map((t) => ({ value: t.id, label: t.label, icon: t.icon }))}
          value={tab}
          onChange={switchTab}
          ariaLabel="设置分区"
        />
      </div>

      {tab === 'overview' && (
        <div className="v3-stack v3-settings-panel">
          <Card variant="aurora" className="v3-settings-overview">
            <CardHead
              icon={<Sparkles size={16} />}
              title="学习数据一览"
              sub="实时读取本地档案，掌握复习资产与今日投入"
              actions={<Badge tone="primary">本地实时</Badge>}
            />
            <div className="v3-settings-stats">
              {tiles.map((t) => {
                const Icon = t.icon
                return (
                  <Tile key={t.label} variant="well" className={`v3-settings-stat is-${t.tone}`}>
                    <div className="v3-tile__label"><Icon size={15} /> {t.label}</div>
                    <div className="v3-tile__value">
                      {liveLoading && t.label === '今日学习' ? <Skeleton width={58} height={34} /> : <AnimatedNumber value={t.val} />}
                    </div>
                    <div className="v3-tile__hint">{t.hint}</div>
                  </Tile>
                )
              })}
            </div>
            {liveError && (
              <Alert tone="danger" className="v3-settings-alert">
                实时学习数据获取失败：后端未启动或网络异常。本地档案统计仍正常，启动后端后自动恢复今日时长等实时数据。
              </Alert>
            )}
          </Card>

          <Card>
            <CardHead
              icon={<Target size={16} />}
              title="备考目标"
              sub="用于仪表盘倒计时、AI 助手画像与规划建议"
            />
            <div className="v3-grid v3-grid-2 v3-settings-formgrid">
              <Field
                label="目标院校"
                hint={schoolOptions.length ? `可从院校库 ${schoolOptions.length} 所中选择，也可手动输入` : '输入目标院校名称'}
              >
                <Input
                  list="v3-settings-school-options"
                  aria-label="目标院校"
                  value={form.school}
                  onChange={(e) => setForm({ ...form, school: e.target.value })}
                  placeholder={schoolOptions.length ? '输入院校名称，或从候选中选择' : '输入目标院校名称'}
                />
                <datalist id="v3-settings-school-options">
                  {schoolOptions.map((n) => <option key={n} value={n} />)}
                </datalist>
              </Field>
              <Field label="报考专业">
                <Input
                  aria-label="报考专业"
                  value={form.major}
                  onChange={(e) => setForm({ ...form, major: e.target.value })}
                  placeholder="专业名称（专业代码）"
                />
              </Field>
              <Field
                label="考研届数"
                hint={`${calYear ? `${calYear} 届` : '未配置'} · 指入学年份，初试在上一年 12 月`}
              >
                <Select
                  aria-label="考研届数"
                  value={calYear}
                  disabled={calSaving}
                  onChange={(e) => applyExamYear(e.target.value)}
                >
                  {!calYear && <option value="">未配置</option>}
                  {(cal?.year_options || []).map((y) => (
                    <option key={y} value={y}>{y} 届</option>
                  ))}
                </Select>
              </Field>
              <Field
                label="初试日期"
                hint={cal ? `${cal.source}${cal.is_official ? '' : ' · 仅供参考，以研招网公告为准'}` : undefined}
              >
                <Input
                  type="date"
                  aria-label="初试日期"
                  value={form.examDate}
                  onChange={(e) => setForm({ ...form, examDate: e.target.value })}
                />
              </Field>
              <Field label="目标分数">
                <Input
                  type="number"
                  aria-label="目标分数"
                  value={form.targetScore ?? ''}
                  onChange={(e) => setForm({ ...form, targetScore: Number(e.target.value) })}
                />
              </Field>
            </div>
            {cal && (
              <div className="v3-settings-calcaption">
                距初试
                <b className={cal.days_left < 0 ? 'is-muted' : 'is-danger'}>
                  {cal.days_left < 0 ? ` 已过 ${-cal.days_left} 天` : ` ${cal.days_left} 天`}
                </b>
                {cal.signup_hint ? ` · 报名窗口 ${cal.signup_hint}` : ''}
                {cal.official_date && cal.official_date !== cal.exam_date ? (
                  <em> · 教育部公布的是 {cal.official_date}</em>
                ) : null}
              </div>
            )}
            <div className="v3-card__foot v3-settings-foot">
              <span className="v3-caption">保存后会同步写入后端目标档案，避免被旧值覆盖。</span>
              <Button onClick={saveSettings}>保存设置</Button>
            </div>
          </Card>

          <SubjectSettingsV3 />
        </div>
      )}

      {isAdmin && tab === 'ai' && (
        <div className="v3-stack v3-settings-panel">
          <Card>
            <CardHead
              icon={<Cpu size={16} />}
              title="本地模型（Ollama）"
              sub="离线 AI 引擎 · 数据不出网 · 简单问题本地秒回，复杂问题自动走在线 API"
              actions={
                localModel.checking
                  ? <Badge>检测中</Badge>
                  : localModel.available ? <Badge tone="success">已连接</Badge> : <Badge tone="danger">未启动</Badge>
              }
            />
            <div className="v3-settings-rowwrap">
              <span className="v3-settings-statusline">
                服务状态：{localModel.checking ? '检测中…' : localModel.available ? '已连接' : '未启动 / 未安装'}
              </span>
              <Button variant="outline" size="sm" icon={<RefreshCw size={14} />} onClick={checkLocalModel} disabled={localModel.checking}>
                {localModel.checking ? '检测中…' : '重新检测'}
              </Button>
              <Button variant="tonal" size="sm" icon={<Wand size={14} />} onClick={testLocalModel} disabled={localTesting || !localModel.available}>
                {localTesting ? '测试中…' : '测试模型'}
              </Button>
            </div>
            {localModel.available && localModel.models.length > 0 && (
              <div className="v3-settings-modelchips">
                <span className="v3-caption">已安装模型：</span>
                {localModel.models.map((m, i) => (
                  <Chip key={`${m.name}-${i}`} as="span">{m.name} ({m.size_gb} GB)</Chip>
                ))}
              </div>
            )}
            {localTestResult && localTestResult.success && (
              <div className="v3-settings-testbox">
                <Badge tone="success">测试成功</Badge>
                <p>{localTestResult.response}</p>
                <span>模型：{localTestResult.model} · 生成 {localTestResult.eval_count} tokens · 耗时 {localTestResult.total_duration_ms} ms</span>
              </div>
            )}
            {!localModel.available && !localModel.checking && (
              <div className="v3-settings-hint">
                未检测到 Ollama 服务。请先安装 Ollama（
                <a href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">下载地址</a>
                ），然后运行 <code>ollama run qwen3.5:4b</code> 拉取轻量模型。
                本地模型可处理定义、概念、单词等简单问题，复杂问题自动走在线 API。
              </div>
            )}
          </Card>

          <ModelSelectPanelV3 />
          <AiServiceManagerV3 />
        </div>
      )}

      {tab === 'appearance' && (
        <div className="v3-stack v3-settings-panel">
          <Card>
            <CardHead
              icon={<Cloud size={16} />}
              title="百度网盘授权"
              sub="在「网盘联动」页可扫码 / 授权后浏览同步网盘资料"
              actions={
                panLoading ? <Badge>检测中…</Badge>
                  : panSt.configured ? <Badge tone="success">已配置</Badge> : <Badge tone="warning">未配置</Badge>
              }
            />
            <div className="v3-settings-rowwrap">
              <span className="v3-settings-statusline">
                服务端凭证：{panSt.configured ? `已授权${panSt.appId ? `（AppID ${panSt.appId}）` : ''}` : '未配置'}
              </span>
              {panTok ? (
                <Button
                  variant="danger"
                  size="sm"
                  icon={<Trash size={14} />}
                  onClick={() => { clearPan(); setPanTok(null); toastOk('已清除本机网盘授权') }}
                >
                  清除授权
                </Button>
              ) : (
                <span className="v3-caption">本机未授权，可前往「网盘联动」页完成 OAuth 绑定</span>
              )}
            </div>
            {!panSt.configured && (
              <div className="v3-settings-hint">
                配置方法：在 <code>backend-main-fastapi/.env</code> 中填写百度开放平台个人应用凭证
                （<code>BAIDU_NETDISK_APP_ID</code> / <code>BAIDU_NETDISK_APP_KEY</code> / <code>BAIDU_NETDISK_SECRET_KEY</code>），并重启后端。
              </div>
            )}
          </Card>

          <Card>
            <CardHead
              icon={<Sun size={16} />}
              title="外观主题"
              sub="明色「纸上备考」与暗色「深夜自习」，或跟随系统自动切换"
              actions={
                <Badge tone="primary">
                  {settings.theme === 'dark' ? '深夜自习' : settings.theme === 'system' ? '跟随系统' : '纸上备考'}
                </Badge>
              }
            />
            <Segmented
              ariaLabel="外观主题"
              value={settings.theme}
              onChange={setTheme}
              options={[
                { value: 'light', label: '浅色', icon: <Sun size={15} /> },
                { value: 'dark', label: '深色', icon: <Moon size={15} /> },
                { value: 'system', label: '跟随系统', icon: <Compass size={15} /> },
              ]}
            />
            <p className="v3-settings-smallhint">
              选择「跟随系统」后，主题将随操作系统的亮 / 暗模式实时变化。
            </p>
          </Card>

          <UiCustomizeV3 />
          <LanAccessCardV3 />

          <Card>
            <CardHead
              icon={<Database size={16} />}
              title="数据管理"
              sub="数据存储于本地浏览器（localStorage），可导出 JSON 备份，换设备时导入恢复"
            />
            <div className="v3-settings-rowwrap">
              <Button variant="outline" icon={<Download size={15} />} onClick={exportData}>导出备份</Button>
              <Button variant="outline" icon={<Upload size={15} />} onClick={() => fileRef.current?.click()}>导入备份</Button>
              <Button variant="ghost" icon={<Keyboard size={15} />} onClick={() => setShowShortcuts(true)}>快捷键说明</Button>
              <Button variant="danger" icon={<Trash size={15} />} onClick={() => setShowReset(true)}>重置本地缓存</Button>
              <input
                ref={fileRef}
                type="file"
                accept="application/json,.json"
                aria-label="选择备份文件（JSON）"
                style={{ display: 'none' }}
                onChange={importData}
              />
            </div>
          </Card>

          <Card variant="tonal" className="v3-settings-about">
            <CardHead
              icon={<Rocket size={16} />}
              title="关于本应用"
              sub="硕途 · 综合考研全流程复习规划应用"
            />
            <p>
              通用考研复习工作台：<strong>目标院校、初试日期、备考科目全部由你在上面几栏配置</strong>，
              应用不内置任何学校或专业方向（未配置时各页面显示空态并给出配置入口）。主要模块：
              仪表盘（倒计时 / 今日任务 / 复习提醒）· 任务打卡（日周月视图 / AI 规划）·
              <strong>知识地图</strong>（章节 → 知识点 → 题型三级结构 + 复习进度追踪）·
              文档知识库（扫描版真题 OCR → 分块 → RAG 检索）· 刷题中心与错题本（错题自动挂靠考点）·
              AI 助手（本地 Ollama / DeepSeek 等云端 API 可切换）· 网盘联动（百度网盘授权后经后端代理取流）。
            </p>
            <p>
              技术栈：Vite + React + Zustand + React Router + FastAPI + PostgreSQL（含 pgvector 向量检索）。
              响应式设计，支持电脑 / 平板 / 手机三端。学习数据保存在你自己的数据库里；
              只有两类外部请求：你配置的 AI 服务商，以及百度网盘 —— 两者都经后端转发，密钥不下发浏览器。
            </p>
          </Card>
        </div>
      )}

      {tab === 'account' && (
        <div className="v3-stack v3-settings-panel">
          <AccountSecurityV3 />
          {isAdmin && <UserAdminV3 />}
        </div>
      )}

      <Dialog
        open={showReset}
        title="重置本地缓存"
        sub="只清空浏览器本地副本，不会删除服务器数据库"
        onClose={() => setShowReset(false)}
        footer={(
          <>
            <Button variant="text" onClick={() => setShowReset(false)}>取消</Button>
            <Button variant="danger" onClick={doReset}>确认重置</Button>
          </>
        )}
      >
        <div className="v3-stack" style={{ gap: 12 }}>
          <p className="v3-settings-dialogtext">
            此操作只清空<strong>浏览器本地缓存</strong>里的任务、错题、网盘、卡片等副本，用于把界面恢复到初始空态。
          </p>
          <Alert tone="danger">
            <strong>服务器数据库不会被删除</strong>：后端在线时，下一次同步会把这些记录重新拉回来。
            要真正删除请到对应页面逐条操作。
          </Alert>
          <p className="v3-settings-smallhint">建议先执行「导出备份」再操作。</p>
        </div>
      </Dialog>

      <Dialog
        open={showShortcuts}
        title="键盘快捷键"
        sub="以下为应用中已真实接入的快捷键，部分仅在对应页面生效"
        onClose={() => setShowShortcuts(false)}
        footer={<Button onClick={() => setShowShortcuts(false)}>知道了</Button>}
      >
        <div className="v3-settings-shortcuts">
          {SHORTCUTS.map((s, i) => (
            <div className="v3-settings-shortcut" key={`${s.desc}-${i}`}>
              <div className="v3-settings-keys">
                {s.keys.map((k, j) => (
                  <React.Fragment key={k}>
                    <kbd className="v3-kbd">{k}</kbd>
                    {j < s.keys.length - 1 && <span>+</span>}
                  </React.Fragment>
                ))}
              </div>
              <span className="v3-settings-shortcut__desc">{s.desc}</span>
              <Badge tone="outline">{s.scope}</Badge>
            </div>
          ))}
        </div>
      </Dialog>
    </div>
  )
}

/* ========================================================================== */
/* 备考科目                                                                    */
/* ========================================================================== */
function SubjectSettingsV3() {
  const { isAdmin } = useAuth()
  const [cfg, setCfg] = useState(null)
  const [status, setStatus] = useState('loading')
  const [saving, setSaving] = useState(false)
  const [exam, setExam] = useState([])
  const [support, setSupport] = useState([])
  const [newSubject, setNewSubject] = useState('')
  const [adding, setAdding] = useState(false)
  const [addToLayer, setAddToLayer] = useState('exam')
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState({ exam: false, support: false })

  const load = useCallback(() => {
    setStatus('loading')
    goalsApi.subjects()
      .then((d) => {
        setCfg(d)
        setExam(d.exam_subjects || [])
        setSupport(d.support_subjects || [])
        setStatus('ok')
      })
      .catch(() => setStatus('error'))
  }, [])

  useEffect(() => { load() }, [load])

  const toggle = (list, setList, name) => {
    setList(list.includes(name) ? list.filter((x) => x !== name) : [...list, name])
  }

  const save = async () => {
    setSaving(true)
    try {
      const d = await goalsApi.updateSubjects({ exam_subjects: exam, support_subjects: support })
      setCfg(d)
      setExam(d.exam_subjects || [])
      setSupport(d.support_subjects || [])
      toastOk(d.ignored?.length ? `已保存（忽略无法识别的：${d.ignored.join('、')}）` : '科目配置已保存')
    } catch (e) {
      toastErr(`保存失败：${e.message}`)
    }
    setSaving(false)
  }

  const resetDefault = () => {
    setExam(cfg?.core_defaults || [])
    setSupport(cfg?.major_defaults || [])
  }

  const addCustomSubject = async () => {
    const name = newSubject.trim()
    if (!name) return toast('请输入科目名')
    if (cfg?.all_known?.includes(name) || exam.includes(name) || support.includes(name)) {
      return toast('该科目已存在')
    }
    setAdding(true)
    try {
      await taxonomyApi.createSubject({ subject: name })
      if (addToLayer === 'exam') setExam((l) => [...l, name])
      else setSupport((l) => [...l, name])
      const d = await goalsApi.subjects()
      setCfg(d)
      setNewSubject('')
      toastOk(`已新增自定义科目「${name}」，点击「保存」生效`)
    } catch (e) {
      toastErr(`新增失败：${e.message || '未知错误'}`)
    } finally {
      setAdding(false)
    }
  }

  const dirty = cfg && (
    JSON.stringify([...exam].sort()) !== JSON.stringify([...(cfg.exam_subjects || [])].sort())
    || JSON.stringify([...support].sort()) !== JSON.stringify([...(cfg.support_subjects || [])].sort())
  )

  const groups = [
    { key: 'exam', title: '考试科目', desc: '你实际要考的，计入复习进度与薄弱统计', list: exam, setList: setExam },
    { key: 'support', title: '专业课支撑科目', desc: '可能涉及、要能查资料出题，但不计入进度', list: support, setList: setSupport },
  ]

  const namesFor = (g) => (cfg?.all_known || [])
    .filter((name) => !IRRELEVANT_SUBJECTS.includes(name) || g.list.includes(name))
    .filter((name) => !query.trim() || name.includes(query.trim()))

  const visibleFor = (g) => {
    const all = namesFor(g)
    if (query.trim() || expanded[g.key]) return all
    const chosen = all.filter((n) => g.list.includes(n))
    const rest = all.filter((n) => !g.list.includes(n)).slice(0, 8)
    return [...chosen, ...rest]
  }

  if (status === 'loading') {
    return (
      <Card>
        <CardHead icon={<Book size={16} />} title="备考科目" sub="正在读取科目配置…" />
        <div className="v3-stack">
          <Skeleton height={40} />
          <Skeleton height={88} />
          <Skeleton height={88} />
        </div>
      </Card>
    )
  }
  if (status === 'error' || !cfg) {
    return (
      <Card>
        <Empty
          icon={<Book size={24} />}
          title="读取科目配置失败"
          text="请确认后端已启动后重试。科目口径决定进度分母、刷题筛选与 AI 分科路由。"
          action={<Button variant="outline" icon={<RefreshCw size={14} />} onClick={load}>重试</Button>}
        />
      </Card>
    )
  }

  return (
    <Card>
      <CardHead
        icon={<Book size={16} />}
        title="备考科目"
        sub="决定进度统计口径、AI 分科选模型、资料归类与出题范围 —— 改这里不用改代码"
        actions={(
          <div className="v3-settings-actions">
            <Button variant="ghost" size="sm" onClick={resetDefault}>
              {exam.length || support.length ? '恢复建议科目' : '填入建议科目'}
            </Button>
            <Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={load}>重新读取</Button>
            <Button size="sm" onClick={save} disabled={saving || !dirty} loading={saving}>
              {dirty ? '保存' : '已保存'}
            </Button>
          </div>
        )}
      />
      <div className="v3-settings-hint">
        {cfg.using_default
          ? <>还没有配置备考科目：科目层为空，进度分母、刷题筛选与 AI 画像都不替你假设专业方向。
            点「填入建议科目」可一键带上系统已知大纲的 {(cfg.core_defaults || []).length} 个科目，再按实际情况增减；
            {isAdmin ? '预置池里没有的科目用下方「新增自定义科目」。' : '预置池里没有的科目请联系管理员添加。'}</>
          : '已隐藏与多数考研方向无关的预置科目（管理类联考、医学、教育等），如需恢复请勾选对应科目后保存。'}
      </div>

      <Input
        icon={<Search size={15} />}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="搜索科目（如：电路 / 408 / 英语）"
        aria-label="搜索备考科目"
        className="v3-settings-search"
      />

      {groups.map((g) => {
        const all = namesFor(g)
        const visible = visibleFor(g)
        return (
          <div className="v3-settings-subjectgroup" key={g.key}>
            <div className="v3-settings-grouphead">
              <span className="v3-settings-grouptitle">{g.title}</span>
              <span className="v3-settings-groupdesc">{g.desc}</span>
              <Badge tone="primary">已选 {g.list.length}</Badge>
            </div>
            <div className="v3-settings-chips">
              {visible.map((name) => {
                const on = g.list.includes(name)
                const meta = cfg.subject_meta?.[name] || {}
                return (
                  <Chip
                    key={name}
                    active={on}
                    onClick={() => toggle(g.list, g.setList, name)}
                    title={`章节 ${(meta.chapters || []).length} · 题型 ${(meta.question_types || []).join('/')}`}
                  >
                    {on && <CheckCircle size={12} />}
                    {name}
                    <small>{(meta.chapters || []).length}章</small>
                  </Chip>
                )
              })}
              {!query && all.length > visible.length && (
                <Chip className="v3-settings-expand" onClick={() => setExpanded((e) => ({ ...e, [g.key]: true }))}>
                  展开全部 {all.length} 个
                </Chip>
              )}
              {!query && expanded[g.key] && (
                <Chip className="v3-settings-expand" onClick={() => setExpanded((e) => ({ ...e, [g.key]: false }))}>
                  收起
                </Chip>
              )}
              {query && all.length === 0 && (
                <span className="v3-settings-emptymatch">没有匹配「{query}」的科目</span>
              )}
            </div>
          </div>
        )
      })}

      {isAdmin && (
        <div className="v3-settings-subjectgroup">
          <div className="v3-settings-grouphead">
            <span className="v3-settings-grouptitle">新增自定义科目</span>
            <span className="v3-settings-groupdesc">预置池里没有的科目（如另一门专业课），加进来后全站可用</span>
          </div>
          <div className="v3-settings-customrow">
            <Input
              aria-label="新增自定义科目名称"
              placeholder="输入科目名，如：信号与系统 / 自控原理 / 数据结构"
              value={newSubject}
              onChange={(e) => setNewSubject(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addCustomSubject() }}
            />
            <Select
              aria-label="加入的科目层"
              value={addToLayer}
              onChange={(e) => setAddToLayer(e.target.value)}
              options={[
                { value: 'exam', label: '加入考试科目' },
                { value: 'support', label: '加入支撑科目' },
              ]}
            />
            <Button
              icon={<Plus size={14} />}
              onClick={addCustomSubject}
              disabled={adding || !newSubject.trim()}
              loading={adding}
            >
              添加
            </Button>
          </div>
          {(exam.some((s) => !cfg.all_known.includes(s)) || support.some((s) => !cfg.all_known.includes(s))) && (
            <div className="v3-settings-hint">
              含自定义科目：{[...exam, ...support].filter((s) => !cfg.all_known.includes(s)).join('、')}
            </div>
          )}
        </div>
      )}

      <div className="v3-settings-preview">
        <strong>当前口径生效后：</strong>
        <ul>
          <li>复习进度与薄弱考点统计 <b>{exam.length}</b> 科：{exam.join('、') || '（空）'}</li>
          <li>AI 分科选模型覆盖 <b>{exam.length + support.length}</b> 科</li>
          <li>资料可归类到 <b>{cfg.all_known.length}</b> 个科目（含拓展）</li>
        </ul>
      </div>

      <details className="v3-settings-details">
        <summary>这两层的区别是什么？</summary>
        <ul>
          <li><b>考试科目</b>：真正会出现在成绩单上的。知识地图进度、薄弱考点排名只算这几科。</li>
          <li><b>支撑科目</b>：备选院校专业课或补基础用的。能录入、检索、出题、按科目选模型，但不计入复习进度。</li>
          <li>两层的并集 = AI 分科路由的范围。提问时系统会自动识别科目并选对应模型。</li>
        </ul>
      </details>
    </Card>
  )
}

/* ========================================================================== */
/* AI 服务管理                                                                 */
/* ========================================================================== */
function AiServiceManagerV3() {
  const [providers, setProviders] = useState([])
  const [routing, setRouting] = useState(null)
  const [loadErr, setLoadErr] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [draft, setDraft] = useState({
    key: 'deepseek', name: 'DeepSeek', baseUrl: PRESETS[0].baseUrl, model: PRESETS[0].model, apiKey: '',
  })
  const [testBusyId, setTestBusyId] = useState(null)
  const [testResults, setTestResults] = useState({})

  const load = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([aiApi.providers(), aiApi.getRouting().catch(() => null)])
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
    const key = PRESETS.some((x) => x.key === p.provider_type) ? p.provider_type : 'custom'
    setEditingId(p.id)
    setDraft({ key, name: p.name, baseUrl: p.base_url || '', model: p.model_name || '', apiKey: '' })
    setShowEdit(true)
  }

  const onPreset = (key) => {
    const preset = providerPreset(key)
    setDraft((d) => ({ ...d, key, name: preset.name, baseUrl: preset.baseUrl, model: preset.model }))
  }

  const save = async () => {
    if (!draft.name.trim() || !draft.baseUrl.trim() || !draft.model.trim()) {
      return toast('请完整填写名称 / Base URL / 模型')
    }
    if (!editingId && !draft.apiKey.trim() && draft.key !== 'custom' && draft.key !== 'ollama') {
      return toast('新增云端服务需要填写 API Key')
    }
    const body = {
      name: draft.name.trim(),
      provider_type: draft.key === 'custom' ? 'custom' : draft.key,
      base_url: draft.baseUrl.trim().replace(/\/+$/, ''),
      model_name: draft.model.trim(),
      is_enabled: true,
    }
    if (draft.apiKey.trim()) body.api_key = draft.apiKey.trim()
    try {
      if (editingId) {
        await aiApi.updateProvider(editingId, body)
        toastOk('服务已更新')
      } else {
        await aiApi.saveProvider(body)
        toastOk('服务已添加，后端 AI 网关立即可用')
      }
      setShowEdit(false)
      load()
    } catch (e) {
      toastErr(`保存失败：${e.message}`)
    }
  }

  const runTest = async (p) => {
    setTestBusyId(p.id)
    try {
      const r = await aiApi.testProvider(p.id)
      setTestResults((s) => ({
        ...s,
        [p.id]: r.success
          ? { ok: true, latency: r.response_time, preview: (r.preview || '').slice(0, 80) }
          : { ok: false, error: r.error || '未知错误', latency: r.response_time },
      }))
      toast(r.success ? `测试成功 · ${r.response_time}s` : `测试失败：${(r.error || '').slice(0, 60)}`)
    } catch (e) {
      setTestResults((s) => ({ ...s, [p.id]: { ok: false, error: e.message } }))
      toastErr(`测试失败：${e.message}`)
    }
    setTestBusyId(null)
  }

  const onRouting = async (mode) => {
    try {
      await aiApi.setRouting(mode)
      toastOk('路由模式已切换，立即生效')
      load()
    } catch (e) {
      toastErr(`切换失败：${e.message}`)
    }
  }

  const toggleProvider = async (p) => {
    try {
      await aiApi.updateProvider(p.id, { is_enabled: !p.is_enabled })
      load()
    } catch (e) {
      toastErr(e.message)
    }
  }

  const makeDefault = async (p) => {
    try {
      await aiApi.updateProvider(p.id, { is_default: true })
      toastOk(`已设为默认：${p.name}`)
      load()
    } catch (e) {
      toastErr(e.message)
    }
  }

  const removeProvider = async (p) => {
    try {
      await aiApi.removeProvider(p.id)
      toastOk('已删除该服务')
      load()
    } catch (e) {
      toastErr(e.message)
    }
  }

  return (
    <Card>
      <CardHead
        icon={<Sparkles size={16} />}
        title="AI 服务管理"
        sub="服务商配置 · 一键测试 · 本地/云端路由 · 后端统一调用"
        actions={<Button size="sm" icon={<Plus size={14} />} onClick={openAdd}>添加服务</Button>}
      />

      {routing && (
        <div className="v3-settings-routing">
          <div>
            <b>AI 路由模式</b>
            <span>控制答疑 / 组卷 / 解析等所有 AI 调用走本地 Ollama 还是云端 API，切换立即生效</span>
          </div>
          <div className="v3-settings-routing__opts">
            {(routing.options || []).map((o) => (
              <Chip
                key={o.mode}
                active={routing.mode === o.mode}
                onClick={() => onRouting(o.mode)}
                title={o.label}
              >
                {o.label}
              </Chip>
            ))}
          </div>
        </div>
      )}

      {loadErr && (
        <Alert tone="danger" className="v3-settings-alert">
          后端服务不可达，AI 配置读取失败。请确认后端已启动。
          <Button variant="ghost" size="sm" onClick={load}>重试</Button>
        </Alert>
      )}

      {providers.length === 0 && !loadErr && (
        <div className="v3-settings-hint">尚未配置任何云端 AI 服务。本地 Ollama 模型无需在此配置，开箱即用。</div>
      )}

      <div className="v3-settings-providers">
        {providers.map((p) => {
          const t = testResults[p.id]
          return (
            <div key={p.id} className={`v3-settings-provider${p.is_default ? ' is-default' : ''}`}>
              <div className="v3-settings-provider__head">
                <div className="v3-settings-provider__name">
                  <Server size={15} />
                  <span>{p.name}</span>
                  {p.is_default && <Badge tone="primary">默认</Badge>}
                  {!p.is_enabled && <Badge tone="outline">停用</Badge>}
                  {p.provider_type !== 'ollama' && !p.has_api_key && <Badge tone="warning">未配 Key</Badge>}
                </div>
                <code>{p.model_name}</code>
              </div>
              <div className="v3-settings-provider__url">{p.base_url}</div>
              {t && (
                <div className={`v3-settings-testresult${t.ok ? ' is-ok' : ' is-fail'}`}>
                  {t.ok ? `连通正常 · ${t.latency}s · 回复：${t.preview}` : `错误：${t.error}`}
                </div>
              )}
              <div className="v3-settings-provider__actions">
                {!p.is_default && (
                  <Button variant="ghost" size="sm" onClick={() => makeDefault(p)}>设为默认</Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => toggleProvider(p)}>
                  {p.is_enabled ? '停用' : '启用'}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => openEdit(p)}>编辑</Button>
                <Button
                  variant="tonal"
                  size="sm"
                  loading={testBusyId === p.id}
                  onClick={() => runTest(p)}
                >
                  测试接口
                </Button>
                <Button variant="ghost" size="sm" className="is-danger" onClick={() => removeProvider(p)}>删除</Button>
              </div>
            </div>
          )
        })}
      </div>

      <p className="v3-settings-smallhint">
        支持 DeepSeek、豆包（火山方舟）、通义千问、智谱、OpenAI 等 OpenAI 兼容接口。
        配置保存在本机数据库并由后端统一调用（无跨域问题）；「测试接口」从服务端发起真实对话验证。
        本地 Ollama 模型自动可用，无需在此添加。Key 不回传前端，编辑时留空即保持不变。
      </p>

      <Dialog
        open={showEdit}
        title={editingId ? '编辑 AI 服务' : '添加 AI 服务'}
        sub="云端服务经后端网关调用，API Key 只写不读"
        onClose={() => setShowEdit(false)}
        footer={(
          <>
            <Button variant="text" onClick={() => setShowEdit(false)}>取消</Button>
            <Button onClick={save}>保存</Button>
          </>
        )}
      >
        <div className="v3-stack">
          <Field label="服务商预设">
            <Select value={draft.key} onChange={(e) => onPreset(e.target.value)}>
              {PRESETS.map((pr) => (
                <option key={pr.key} value={pr.key}>{pr.name}{pr.vision ? '（支持视觉）' : ''}</option>
              ))}
            </Select>
          </Field>
          <Field label="显示名称">
            <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="如：我的 DeepSeek" />
          </Field>
          <Field label="Base URL">
            <Input value={draft.baseUrl} onChange={(e) => setDraft({ ...draft, baseUrl: e.target.value })} placeholder="https://api.deepseek.com" />
          </Field>
          <Field label="模型名称">
            <Input value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} placeholder="deepseek-chat" />
          </Field>
          <Field label={editingId ? 'API Key（留空 = 保持原 Key 不变）' : 'API Key'}>
            <Input
              type="password"
              autoComplete="off"
              value={draft.apiKey}
              onChange={(e) => setDraft({ ...draft, apiKey: e.target.value })}
              placeholder="sk-…"
              icon={<KeyRound size={15} />}
            />
          </Field>
        </div>
      </Dialog>
    </Card>
  )
}

/* ========================================================================== */
/* 模型选型                                                                    */
/* ========================================================================== */
function ModelSelectPanelV3() {
  const [rep, setRep] = useState(null)
  const [status, setStatus] = useState('loading')
  const [seg, setSeg] = useState('subject')
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
    const order = { perfect: 0, ok: 1, tight: 2, too_big: 3, unknown: 2 }
    local.sort((a, b) => (order[a.fit.level] ?? 9) - (order[b.fit.level] ?? 9) || b.reasoning - a.reasoning)
    return { local, cloud }
  }, [rep])

  if (status === 'loading') {
    return (
      <Card>
        <CardHead icon={<HardDrive size={16} />} title="模型选型" sub="正在读取硬件与模型档案…" />
        <div className="v3-stack">
          <Skeleton height={80} />
          <Skeleton height={140} />
        </div>
      </Card>
    )
  }
  if (status === 'error' || !rep) {
    return (
      <Card>
        <Empty
          icon={<HardDrive size={24} />}
          title="读取硬件与模型档案失败"
          text="请确认后端已启动后重试。模型选型会按本机显存判断能否运行本地模型。"
          action={<Button variant="outline" icon={<RefreshCw size={14} />} onClick={load}>重试</Button>}
        />
      </Card>
    )
  }

  const hw = rep.hardware || {}
  const tierLabel = {
    cpu: '无独显（只能走云端 API）',
    entry: '入门级显存（4-6GB）',
    mainstream: '主流级显存（6-9GB）',
    advanced: '进阶级显存（9-16GB）',
    high: '高端显存（16GB+）',
  }[rep.hardware_tier] || rep.hardware_tier

  return (
    <Card>
      <CardHead
        icon={<HardDrive size={16} />}
        title="模型选型"
        sub="按本机显存判断能不能跑，按科目判断该用哪个 —— 不看排行榜参数量"
        actions={<Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={load}>重新探测</Button>}
      />

      <div className="v3-settings-hw">
        <div className="v3-settings-hw__main">
          <span className="v3-settings-hw__gpu">{hw.gpu_name || '未检测到独立显卡'}</span>
          <span className="v3-settings-hw__tier">{tierLabel}</span>
        </div>
        <div className="v3-settings-hw__stats">
          <div><span>显存</span><b>{hw.vram_gb || 0} GB</b></div>
          <div><span>内存</span><b>{hw.ram_gb || '—'} GB</b></div>
          <div><span>已装模型</span><b>{rep.installed_models?.length || 0} 个</b></div>
        </div>
        {!hw.cuda_available && (
          <div className="v3-settings-hw__warn">
            未检测到可用 CUDA 环境。本地模型无法加速，建议先装 Ollama，或直接使用云端 API。
          </div>
        )}
      </div>

      <Segmented
        ariaLabel="模型视图"
        value={seg}
        onChange={setSeg}
        options={[
          { value: 'subject', label: '分科建议', icon: <Wand size={14} /> },
          { value: 'local', label: `本地模型 (${groups.local.length})`, icon: <Cpu size={14} /> },
          { value: 'cloud', label: `云端模型 (${groups.cloud.length})`, icon: <Cloud size={14} /> },
        ]}
        className="v3-settings-modelswitch"
      />

      {seg === 'subject' && (
        <div className="v3-settings-subjectplan">
          {(rep.subject_plan || []).map((s) => {
            const top = s.recommendations[0]
            const alt = s.recommendations.slice(1)
            return (
              <div className="v3-settings-subjectrow" key={s.subject}>
                <div className="v3-settings-subjectrow__name">
                  {s.subject}
                  <span>{s.task_desc}</span>
                </div>
                <div className="v3-settings-subjectrow__pick">
                  {top ? (
                    <>
                      <b>{top.name}</b>
                      <Badge tone="success">{top.fit.label}</Badge>
                      {top.subject_score > 0 && <span className="v3-caption">强项 {top.subject_score}/5</span>}
                    </>
                  ) : <span className="v3-caption">暂无推荐</span>}
                </div>
                {alt.length > 0 && (
                  <div className="v3-settings-subjectrow__alt">
                    备选：{alt.map((a) => `${a.name}（${a.fit.label}）`).join(' · ')}
                  </div>
                )}
              </div>
            )
          })}
          <div className="v3-settings-batch">
            <div className="v3-settings-batch__title">批量任务建议（文档处理 / OCR 纠错）</div>
            {(rep.batch_plan || []).map((b) => (
              <div className="v3-settings-batch__row" key={b.task}>
                <span>{b.task_desc}</span>
                <b>{b.recommendations[0]?.name || '暂无'} — 批量场景优先速度，选小模型更划算</b>
              </div>
            ))}
          </div>
        </div>
      )}

      {seg !== 'subject' && (
        <div className="v3-settings-modellist">
          {groups[seg].map((m) => {
            const pullCmd = m.ollama_name ? `ollama pull ${m.ollama_name}` : ''
            return (
              <div className={`v3-settings-model${m.installed ? ' is-installed' : ''}`} key={m.key}>
                <div className="v3-settings-model__head">
                  <b>{m.name}</b>
                  <span className="v3-settings-model__family">{m.family}</span>
                  {m.installed
                    ? <Badge tone="success"><CheckCircle size={12} /> 已安装</Badge>
                    : m.local ? <Badge tone="primary">{m.fit.label}</Badge> : null}
                  {!m.local && <Badge tone="outline">云端 API</Badge>}
                </div>
                <div className="v3-settings-model__meta">
                  {m.local && <span>{m.params_b}B</span>}
                  {m.local && <span>权重 ≈ {m.weights_gb}GB</span>}
                  {m.local && <span>总需求 ≈ {m.required_gb}GB</span>}
                  <span>上下文 {m.context_k}K</span>
                  <span>中文 {'★'.repeat(m.chinese)}{'☆'.repeat(5 - m.chinese)}</span>
                  <span>推理 {'★'.repeat(m.reasoning)}{'☆'.repeat(5 - m.reasoning)}</span>
                  {m.local && <span>速度 {'★'.repeat(m.speed)}{'☆'.repeat(5 - m.speed)}</span>}
                </div>
                {m.strengths_cn && Object.keys(m.strengths_cn).length > 0 && (
                  <div className="v3-settings-model__strengths">
                    {Object.entries(m.strengths_cn).map(([subj, score]) => (
                      <Chip as="span" key={subj} title={`强项评分 ${score}/5`}>{subj} {score}</Chip>
                    ))}
                  </div>
                )}
                <div className="v3-settings-model__note">{m.note}</div>
                {m.local && m.fit.level !== 'too_big' && !m.installed && pullCmd && (
                  <div className="v3-settings-model__cmd">
                    <code>{pullCmd}</code>
                    <Button variant="ghost" size="sm" onClick={() => copy(pullCmd)}>
                      {copied === pullCmd ? '已复制' : '复制'}
                    </Button>
                  </div>
                )}
                {m.local && m.fit.level === 'too_big' && (
                  <div className="v3-settings-model__blocked">{m.fit.detail}</div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {copied === 'FAIL' && <div className="v3-settings-hint">复制失败，请手动输入命令</div>}

      <details className="v3-settings-details">
        <summary>显存是怎么估算的？</summary>
        <ul>
          <li>权重 = 参数量(B) × 量化字节数（Q4_K_M ≈ 0.58 GB/B，Q8 ≈ 1.07）</li>
          <li>总需求 = 权重 + KV cache + 运行时开销（估算偏保守）</li>
          <li>可用显存 = 显卡显存 − 系统预留（8GB 卡按 0.8GB 预留）</li>
          <li>需求 ≤ 可用 × 0.85 → 完美适配；≤ 可用 → 可以运行；再高 → 勉强/不足</li>
          <li>判定依据是 <b>显存</b>，不是排行榜分数 —— 云端 700B+ 的模型在这台机器上永远「显存不足」。</li>
        </ul>
      </details>
    </Card>
  )
}

/* ========================================================================== */
/* 界面自定义                                                                  */
/* ========================================================================== */
function UiGroup({ title, sub, items, idOf, labelOf, layout, hiddenKey, orderKey }) {
  const hiddenSet = layout[hiddenKey] || []
  const order = layout[orderKey] || []
  const ordered = order.length
    ? [...items].sort((a, b) => {
      const ia = order.indexOf(idOf(a))
      const ib = order.indexOf(idOf(b))
      return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib)
    })
    : items
  const allIds = items.map(idOf)
  return (
    <div className="v3-settings-uigroup">
      <div className="v3-settings-uigroup__head">
        <div>
          <b>{title}</b>
          {sub && <span>{sub}</span>}
        </div>
        <Badge tone="outline">已隐藏 {hiddenSet.length}</Badge>
      </div>
      <div className="v3-settings-uirows">
        {ordered.map((it) => {
          const id = idOf(it)
          const off = hiddenSet.includes(id)
          return (
            <div key={id} className={`v3-settings-uirow${off ? ' is-off' : ''}`}>
              <Switch
                checked={!off}
                onChange={() => toggleHidden(hiddenKey, id)}
                label={`${labelOf(it)} 显示`}
              />
              <span className="v3-settings-uirow__label">{labelOf(it)}</span>
              {orderKey && (
                <span className="v3-settings-uirow__order">
                  <IconButton
                    label={`${labelOf(it)} 上移`}
                    size="sm"
                    icon={<ChevronUp size={14} />}
                    onClick={() => moveInOrder(orderKey, id, 'up', allIds)}
                  />
                  <IconButton
                    label={`${labelOf(it)} 下移`}
                    size="sm"
                    icon={<ChevronDown size={14} />}
                    onClick={() => moveInOrder(orderKey, id, 'down', allIds)}
                  />
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function UiCustomizeV3() {
  const layout = useUiLayout()
  const setGlobalSubject = useStore((s) => s.setGlobalSubject)
  return (
    <Card>
      <CardHead
        icon={<SlidersHorizontal size={16} />}
        title="界面自定义"
        sub="勾选显示 / 隐藏；导航分组支持上下调整顺序。偏好仅保存在本机浏览器，不影响其他设备"
        actions={(
          <div className="v3-row" style={{ gap: 8 }}>
            <Button
              variant="tonal"
              size="sm"
              title="清空全局学科选择并恢复默认导航布局，界面回到全新初始状态"
              onClick={() => { setGlobalSubject(''); resetUiLayout(); toastOk('展示内容已重置为全新默认') }}
            >
              重置展示内容
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => { resetUiLayout(); toastOk('界面布局已恢复默认') }}
            >
              恢复默认布局
            </Button>
          </div>
        )}
      />
      <div className="v3-settings-uigroups">
        <UiGroup
          title="顶部导航分组"
          sub="隐藏的分组不再出现在顶部导航；页面本身仍可通过 Ctrl+K 或直达链接进入"
          items={NAV_MODULE_ITEMS}
          idOf={(m) => m.key}
          labelOf={(m) => m.title}
          layout={layout}
          hiddenKey="navHidden"
          orderKey="navOrder"
        />
        <UiGroup
          title="导航「其他」入口"
          sub="这一组只支持隐藏（顺序固定）"
          items={NAV_OTHER_ITEMS}
          idOf={(n) => n.to}
          labelOf={(n) => n.label}
          layout={layout}
          hiddenKey="otherHidden"
          orderKey=""
        />
        <UiGroup
          title="仪表盘区块"
          sub="这一组只支持隐藏（版面成对排布，顺序固定）"
          items={DASH_SECTIONS}
          idOf={(s) => s.id}
          labelOf={(s) => s.label}
          layout={layout}
          hiddenKey="dashHidden"
          orderKey=""
        />
      </div>
    </Card>
  )
}

/* ========================================================================== */
/* 手机 / 局域网访问                                                           */
/* ========================================================================== */
function LanAccessCardV3() {
  const [info, setInfo] = useState(null)
  const [status, setStatus] = useState('loading')
  const [isPhone, setIsPhone] = useState(false)

  const load = () => {
    setStatus('loading')
    systemApi.accessInfo()
      .then((d) => { setInfo(d); setStatus('ok') })
      .catch(() => setStatus('error'))
  }

  useEffect(() => {
    setIsPhone(/Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent))
    load()
  }, [])

  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
      setInfo((s) => ({ ...s, _copied: text }))
      setTimeout(() => setInfo((s) => ({ ...s, _copied: '' })), 1800)
    } catch {
      setInfo((s) => ({ ...s, _copied: 'FAIL' }))
      setTimeout(() => setInfo((s) => ({ ...s, _copied: '' })), 1800)
    }
  }

  if (status === 'loading') {
    return (
      <Card>
        <CardHead icon={<Compass size={16} />} title="手机 / 平板访问" sub="正在读取网络信息…" />
        <Skeleton height={120} />
      </Card>
    )
  }
  if (status === 'error' || !info) {
    return (
      <Card>
        <Empty
          icon={<Compass size={24} />}
          title="网络信息读取失败"
          text="请确认后端已启动后重试。把电脑当服务器，手机连同一 WiFi 即可访问。"
          action={<Button variant="outline" onClick={load}>重试</Button>}
        />
      </Card>
    )
  }

  const lanReady = info.exposed && info.lan_url

  return (
    <Card>
      <CardHead
        icon={<Compass size={16} />}
        title="手机 / 平板访问"
        sub="把电脑当服务器，手机连同一 WiFi 即可打开，用来整理错题、拍照 OCR"
        actions={<Badge tone={lanReady ? 'success' : 'outline'}>{lanReady ? '局域网已开放' : '仅本机'}</Badge>}
      />
      <div className="v3-settings-lan">
        <div className="v3-settings-lan__info">
          <div className="v3-settings-lanrow">
            <span>本机</span>
            <code>{info.local_url}</code>
            <Button variant="ghost" size="sm" onClick={() => copy(info.local_url)}>复制</Button>
          </div>
          <div className="v3-settings-lanrow">
            <span>局域网</span>
            {lanReady
              ? <code className="is-strong">{info.lan_url}</code>
              : <code className="is-muted">未开放（HOST={info.host}）</code>}
            {lanReady && <Button variant="ghost" size="sm" onClick={() => copy(info.lan_url)}>复制</Button>}
          </div>
          <div className="v3-settings-lanrow">
            <span>访问密码</span>
            <Badge tone={info.auth_enabled ? 'success' : 'warning'}>{info.auth_enabled ? '已开启' : '未设置'}</Badge>
          </div>
          {info.all_ips && info.all_ips.length > 1 && (
            <div className="v3-settings-lanmulti">
              <span>多网卡，上面的不通可试：</span>
              {info.all_ips.map((it) => (
                <div key={it.ip} className="v3-settings-lanrow">
                  <code>{`http://${it.ip}:${info.port}`}</code>
                  <em>{it.source}</em>
                </div>
              ))}
            </div>
          )}
          {info._copied && (
            <div className="v3-settings-copied">
              {info._copied === 'FAIL' ? '复制失败，请手动输入地址' : '已复制到剪贴板'}
            </div>
          )}
        </div>
        <div className="v3-settings-lan__qr">
          {info.qr_svg ? (
            <>
              <img src={info.qr_svg} alt="手机访问二维码" width="150" height="150" />
              <span>手机扫码直接打开</span>
            </>
          ) : (
            <div className="v3-settings-lan__qrempty">
              {lanReady ? '二维码不可用' : '开放局域网访问后显示二维码'}
            </div>
          )}
        </div>
      </div>
      {isPhone && (
        <Alert tone="success" className="v3-settings-alert">
          你正在手机上访问本平台，可以直接用「错题本 → 拍照收录」整理错题。
        </Alert>
      )}
      {info.tips && info.tips.length > 0 && (
        <details className="v3-settings-details">
          <summary>连不上？点这里看排查提示（{info.tips.length} 条）</summary>
          <ul>{info.tips.map((t, i) => <li key={i}>{t.replace(/\*\*/g, '')}</li>)}</ul>
        </details>
      )}
    </Card>
  )
}

/* ========================================================================== */
/* 账号与安全                                                                  */
/* ========================================================================== */
const MIN_PASSWORD = 8

function AccountSecurityV3() {
  const { user, changePassword, logout } = useAuth()
  const [form, setForm] = useState({ old: '', next: '', confirm: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    if (form.next.length < MIN_PASSWORD) return setErr(`新密码至少 ${MIN_PASSWORD} 位`)
    if (form.next !== form.confirm) return setErr('两次输入的新密码不一致')
    setBusy(true)
    try {
      await changePassword(form.old, form.next)
      setForm({ old: '', next: '', confirm: '' })
      toastOk('密码已修改，其他设备上的登录已失效')
    } catch (e2) {
      setErr(e2?.message || '修改失败')
    } finally {
      setBusy(false)
    }
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  return (
    <Card>
      <CardHead
        icon={<Shield size={16} />}
        title="账号与安全"
        sub={user ? `当前账号：${user.display_name || user.username}（${user.role === 'admin' ? '管理员' : '普通用户'}）` : '未登录'}
        actions={(
          <div className="v3-settings-actions">
            {user && <Avatar name={user.display_name || user.username} />}
            <Button variant="ghost" size="sm" icon={<LogOut size={14} />} onClick={() => logout()}>退出登录</Button>
          </div>
        )}
      />
      <form onSubmit={submit}>
        <div className="v3-grid v3-grid-2 v3-settings-formgrid">
          <Field label="原密码">
            <Input
              type="password"
              autoComplete="current-password"
              value={form.old}
              onChange={set('old')}
              required
              icon={<Lock size={15} />}
            />
          </Field>
          <div />
          <Field label="新密码" hint={`至少 ${MIN_PASSWORD} 位`}>
            <Input
              type="password"
              autoComplete="new-password"
              value={form.next}
              onChange={set('next')}
              required
              icon={<KeyRound size={15} />}
            />
          </Field>
          <Field label="确认新密码">
            <Input
              type="password"
              autoComplete="new-password"
              value={form.confirm}
              onChange={set('confirm')}
              required
              icon={<KeyRound size={15} />}
            />
          </Field>
        </div>
        {err && <Alert tone="danger" className="v3-settings-alert">{err}</Alert>}
        <div className="v3-card__foot v3-settings-foot">
          <span className="v3-caption">修改成功后，其他设备上的登录会立即失效。</span>
          <Button type="submit" loading={busy}>修改密码</Button>
        </div>
      </form>
    </Card>
  )
}

/* ========================================================================== */
/* 用户管理（管理员）                                                           */
/* ========================================================================== */
function UserAdminV3() {
  const { user: me } = useAuth()
  const [confirm, confirmDialog] = useConfirm()
  const [rows, setRows] = useState(null)
  const [loadErr, setLoadErr] = useState('')
  const [form, setForm] = useState(EMPTY_USER_FORM)
  const [busy, setBusy] = useState(false)
  const [secret, setSecret] = useState(null)
  const [showDeleted, setShowDeleted] = useState(false)

  const load = useCallback(async () => {
    setLoadErr('')
    try {
      const r = await adminUsersApi.list({
        page: 1,
        page_size: 200,
        ...(showDeleted ? { include_deleted: true } : {}),
      })
      setRows(r?.items || [])
    } catch (e) {
      setLoadErr(e?.message || '加载失败')
      setRows([])
    }
  }, [showDeleted])

  useEffect(() => { load() }, [load])

  const replaceRow = (u) => setRows((rs) => rs.map((r) => (r.id === u.id ? u : r)))

  const create = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      const body = { username: form.username.trim(), role: form.role }
      if (form.display_name.trim()) body.display_name = form.display_name.trim()
      if (form.password) body.password = form.password
      const r = await adminUsersApi.create(body)
      setRows((rs) => [...rs, r.user])
      setForm(EMPTY_USER_FORM)
      setSecret({
        username: r.user.username,
        password: r.temporary_password || form.password,
        generated: !!r.temporary_password,
      })
      toastOk(`已创建用户 ${r.user.username}`)
    } catch (e2) {
      toastErr(`创建失败：${e2?.message || e2}`)
    } finally {
      setBusy(false)
    }
  }

  const patch = async (u, body, okMsg) => {
    try {
      replaceRow(await adminUsersApi.update(u.id, body))
      toastOk(okMsg)
    } catch (e) {
      toastErr(`操作失败：${e?.message || e}`)
    }
  }

  const toggleActive = async (u) => {
    if (u.is_active) {
      const ok = await confirm({
        title: '禁用用户',
        message: `禁用后 ${u.username} 的所有会话立即失效，确认？`,
        confirmText: '禁用',
        danger: true,
      })
      if (!ok) return
    }
    patch(u, { is_active: !u.is_active }, u.is_active ? '已禁用' : '已启用')
  }

  const reset = async (u) => {
    const ok = await confirm({
      title: '重置密码',
      message: `将为 ${u.username} 生成临时密码，其下次登录须修改，确认？`,
      confirmText: '重置',
      danger: true,
    })
    if (!ok) return
    try {
      const r = await adminUsersApi.resetPassword(u.id)
      replaceRow(r.user)
      setSecret({ username: r.user.username, password: r.temporary_password, generated: true })
    } catch (e) {
      toastErr(`重置失败：${e?.message || e}`)
    }
  }

  const remove = async (u) => {
    const ok = await confirm({
      title: '删除用户',
      message: `删除后 ${u.username} 将无法登录，其所有会话立即失效。这是软删除，勾选「显示已删除」可以随时恢复。确认删除？`,
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await adminUsersApi.remove(u.id)
      if (showDeleted) await load()
      else setRows((rs) => rs.filter((r) => r.id !== u.id))
      toastOk(`已删除用户 ${u.username}`)
    } catch (e) {
      toastErr(`删除失败：${e?.message || e}`)
    }
  }

  const restore = async (u) => {
    try {
      replaceRow(await adminUsersApi.restore(u.id))
      toastOk(`已恢复用户 ${u.username}`)
    } catch (e) {
      toastErr(`恢复失败：${e?.message || e}`)
    }
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  return (
    <Card>
      <CardHead
        icon={<User size={16} />}
        title="用户管理"
        sub="创建账号、调整角色、禁用与重置密码；新账号首次登录须修改密码。删除为软删除，可恢复"
        actions={<Badge tone="primary">{rows ? `${rows.length} 个账号` : '加载中'}</Badge>}
      />

      <form className="v3-settings-userform" onSubmit={create}>
        <Field label="用户名">
          <Input
            aria-label="用户名"
            placeholder="用户名（字母/数字/_.-）"
            value={form.username}
            onChange={set('username')}
            required
            minLength={2}
            maxLength={64}
            pattern="[A-Za-z0-9_.\-]+"
          />
        </Field>
        <Field label="显示名">
          <Input
            aria-label="显示名"
            placeholder="显示名（可选）"
            value={form.display_name}
            onChange={set('display_name')}
            maxLength={64}
          />
        </Field>
        <Field label="角色">
          <Select aria-label="角色" value={form.role} onChange={set('role')}>
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </Select>
        </Field>
        <Field label="初始密码" hint="留空自动生成，至少 8 位">
          <Input
            type="password"
            autoComplete="new-password"
            aria-label="初始密码"
            placeholder="初始密码（可选）"
            value={form.password}
            onChange={set('password')}
            minLength={8}
          />
        </Field>
        <Button type="submit" loading={busy} icon={<Plus size={14} />}>新建用户</Button>
      </form>

      {secret && (
        <Alert tone="warning" className="v3-settings-secret">
          <div>
            {secret.generated ? (
              <>用户 <b>{secret.username}</b> 的临时密码：<code>{secret.password}</code>（只显示这一次，请立即转交）</>
            ) : (
              <>用户 <b>{secret.username}</b> 已按你填写的初始密码创建</>
            )}
            <Button variant="ghost" size="sm" onClick={() => setSecret(null)}>我已记下</Button>
          </div>
        </Alert>
      )}

      <div className="v3-settings-deletedtoggle">
        <Switch checked={showDeleted} onChange={setShowDeleted} label="显示已删除用户" />
        <span>显示已删除用户</span>
      </div>

      {rows === null ? (
        <div className="v3-stack">
          <Skeleton height={36} />
          <Skeleton height={36} />
          <Skeleton height={36} />
        </div>
      ) : loadErr ? (
        <Empty
          icon={<User size={24} />}
          title="用户列表加载失败"
          text={loadErr}
          action={<Button variant="outline" onClick={load}>重试</Button>}
        />
      ) : (
        <div className="v3-settings-tablewrap">
          <table className="v3-settings-table">
            <thead>
              <tr>
                <th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>最近登录</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => {
                const self = me && u.id === me.id
                const gone = !!u.deleted_at
                return (
                  <tr key={u.id} className={gone ? 'is-gone' : undefined}>
                    <td>{u.username}{self ? '（我）' : ''}</td>
                    <td>{u.display_name || '—'}</td>
                    <td>
                      <Select
                        aria-label={`${u.username} 的角色`}
                        value={u.role}
                        disabled={gone}
                        onChange={(e) => patch(u, { role: e.target.value }, '角色已更新')}
                      >
                        {Object.entries(ROLE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </Select>
                    </td>
                    <td>
                      {gone
                        ? <Badge tone="danger">已删除</Badge>
                        : <Badge tone={u.is_active ? 'success' : 'danger'}>{u.is_active ? '启用' : '已禁用'}</Badge>}
                      {!gone && u.must_change_password && <Badge tone="warning">待改密</Badge>}
                    </td>
                    <td>{fmtDateTime(u.last_login_at)}</td>
                    <td>
                      <div className="v3-settings-rowactions">
                        {gone ? (
                          <Button variant="ghost" size="sm" onClick={() => restore(u)}>恢复</Button>
                        ) : (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={self && u.is_active}
                              onClick={() => toggleActive(u)}
                            >
                              {u.is_active ? '禁用' : '启用'}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => reset(u)}>重置密码</Button>
                            <Button variant="ghost" size="sm" className="is-danger" disabled={self} onClick={() => remove(u)}>删除</Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {rows.length === 0 && (
            <Empty icon={<User size={24} />} title="暂无用户" text="创建第一个账号，或勾选「显示已删除用户」查看可恢复账号。" />
          )}
        </div>
      )}
      {confirmDialog}
    </Card>
  )
}
