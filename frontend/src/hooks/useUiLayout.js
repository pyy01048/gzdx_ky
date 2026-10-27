/**
 * 界面布局偏好（仪表盘区块 / 导航分组与入口的显隐与排序）。
 *
 * 为什么走 localStorage 而不是后端 settings：
 * 布局偏好是**设备相关**的（笔记本窄屏想收的组，台式机不一定），
 * 而 `/api/settings` 是全局单份、多设备共享；把布局写进去会让一台机器的
 * 整理动作污染另一台。数据类偏好（科目、AI 通道）仍归后端，互不混用。
 *
 * 状态管理沿用本仓库既有模式（见 useSubjectConfig / useUnreadNotices）：
 * 模块级快照 + 版本号 + 监听者集合，任何页面改动全局即时生效，
 * 不引入 zustand 切片（store 的 persist 白名单会整体覆盖 settings，混进去
 * 反而容易被 Settings 页的表单镜像写坏）。
 */
import { useEffect, useState } from 'react'
import { ukey, readMigrated } from '../utils/userKeys'

export const UI_LAYOUT_KEY = 'ui_layout_v1' /* B4：真实键 = `ui_layout_v1:{uid}`，见 load/persist/reloadFromStorage */

/** v3 仪表盘实际渲染的区块（顺序与 bento 版面一致；只有这里列出的 id 可被隐藏） */
export const DASH_SECTIONS = [
  { id: 'hero', label: '顶部倒计时横幅' },
  { id: 'kpi', label: '今日 KPI 环比' },
  { id: 'todo', label: '今日任务' },
  { id: 'trend', label: '学习趋势' },
  { id: 'review', label: '待复习' },
  { id: 'heat', label: '学习热力图' },
  { id: 'goal', label: '目标与分数线' },
  { id: 'focus', label: '专注计时（今日时长）' },
  { id: 'weakness', label: '薄弱考点' },
  { id: 'recommend', label: '今日建议' },
  { id: 'modules', label: '今日模块进度' },
  { id: 'notice', label: '院校公告' },
]

/** 按 order 数组排序；表里没有的 id 保持原始相对顺序追加在末尾（新增功能不会被藏掉） */
export function applyOrder(items, order, key = 'id') {
  if (!Array.isArray(order) || order.length === 0) return [...items]
  const idx = new Map(order.map((id, i) => [id, i]))
  const known = items.filter((it) => idx.has(it[key]))
  const rest = items.filter((it) => !idx.has(it[key]))
  known.sort((a, b) => idx.get(a[key]) - idx.get(b[key]))
  return [...known, ...rest]
}

function normalize(raw) {
  const src = raw && typeof raw === 'object' ? raw : {}
  const arr = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [])
  const dashIds = new Set(DASH_SECTIONS.map((s) => s.id))
  return {
    // 只接受已知 id：手改 localStorage 塞进来的野 id 一律丢弃，
    // 否则区块 hide 判断会被永久缓存拖累。
    dashHidden: arr(src.dashHidden).filter((id) => dashIds.has(id)),
    dashOrder: arr(src.dashOrder).filter((id) => dashIds.has(id)),
    modsHidden: arr(src.modsHidden),
    modsOrder: arr(src.modsOrder),
    navHidden: arr(src.navHidden),
    navOrder: arr(src.navOrder),
    otherHidden: arr(src.otherHidden),
    ready: true,
  }
}

function load() {
  /* readMigrated：首读把旧全局键 ui_layout_v1 一次性迁给当前登录用户 */
  return normalize(readMigrated(UI_LAYOUT_KEY, {}))
}

let prefs = load()
let version = 0
const listeners = new Set()

function persist() {
  try {
    localStorage.setItem(ukey(UI_LAYOUT_KEY), JSON.stringify(prefs))
  } catch {
    /* 隐私模式 / 配额满：内存态仍然可用，不阻塞渲染 */
  }
}

function publish() {
  version += 1
  listeners.forEach((fn) => fn())
}

/* B4（用户数据隔离）：真实键带 uid 后缀。登录/登出/切号时 AuthContext.setUser
   会广播 'userkeys:uid-changed'，这里重建内存快照并广播 —— 否则模块加载时建的
   prefs 还是上一个账号（或未登录态）的布局，硬刷新恢复会话、同页切号会串号。 */
function reloadFromStorage() {
  prefs = load()
  publish()
}
if (typeof window !== 'undefined') {
  window.addEventListener('userkeys:uid-changed', reloadFromStorage)
}

export function getUiLayout() {
  return prefs
}

/** 就地改一项偏好并广播。fn 收到当前 prefs，返回新 prefs。 */
function mutate(fn) {
  prefs = fn(prefs)
  persist()
  publish()
}

export function toggleHidden(scope, id) {
  mutate((p) => {
    const cur = p[scope] || []
    return { ...p, [scope]: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] }
  })
}

/** 在 order 表内把 id 往前/往后挪一格；未入表的 id 先按当前可见顺序补全。 */
export function moveInOrder(scope, id, dir, allIds) {
  mutate((p) => {
    const base = (p[scope] || []).length ? p[scope] : [...(allIds || [])]
    const list = base.includes(id) ? [...base] : [...base, id]
    const i = list.indexOf(id)
    const j = dir === 'up' ? i - 1 : i + 1
    if (i < 0 || j < 0 || j >= list.length) return p
    ;[list[i], list[j]] = [list[j], list[i]]
    return { ...p, [scope]: list }
  })
}

export function resetUiLayout() {
  prefs = normalize({})
  persist()
  publish()
}

export function subscribeUiLayout(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function useUiLayout() {
  const [, setTick] = useState(0)
  useEffect(() => subscribeUiLayout(() => setTick((t) => t + 1)), [])
  return prefs
}
