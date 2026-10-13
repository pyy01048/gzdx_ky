import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from './Icon'

/* 命令面板数据：路由 + 中文名 + 描述 + 搜索关键词（中英文/拼音，方便模糊搜索）
   顺序与侧边栏 5+1 模块结构一致：先 5 大学习模块，再院校数据中心，最后通用入口。 */
const COMMANDS = [
  // 学习文库
  { to: '/library', label: '学习文库', desc: 'IMA 资料 · 初试/复试 · 知识/试题/单词', kw: ['library', '文库', '资料', 'wenku', 'ima'] },
  { to: '/documents', label: '文档知识库', desc: '资料与知识图谱', kw: ['document', '文档', '资料', 'wendang', 'file'] },
  { to: '/pan', label: '网盘联动', desc: '云盘与同步', kw: ['pan', '网盘', '云盘', 'wangpan', 'cloud'] },
  { to: '/subjects', label: '科目管理', desc: '科目与考纲设置', kw: ['subject', '科目', 'kemubian', 'setting'] },
  // 知识地图
  { to: '/kbmap', label: '知识地图', desc: '章节→知识点→题型与复习进度', kw: ['kb', '知识地图', '考点', '章节', 'zhishi', 'map', 'taxonomy'] },
  { to: '/panorama', label: '知识点全景', desc: '科目→章节→知识点一屏纵览', kw: ['panorama', '全景', 'quanjing', '刷题'] },
  // 题库
  { to: '/quiz-bank', label: '题库管理', desc: '真题地图 · 章节刷题', kw: ['bank', '题库', 'tiku', '真题', 'zhenti'] },
  { to: '/quiz', label: '刷题中心', desc: '题库与错题强化', kw: ['quiz', '刷题', 'shuati', 'test'] },
  { to: '/cards', label: '记忆卡片', desc: 'Anki 式间隔复习', kw: ['card', '卡片', 'kapian', 'flash'] },
  // 单词记忆
  { to: '/words', label: '单词记忆', desc: '单词背诵与发音', kw: ['word', '单词', '词', 'danci', 'vocab'] },
  // 错题复盘
  { to: '/error-review', label: '错题复盘', desc: '错因分布 · 薄弱知识点 · AI 归因分析', kw: ['error', 'review', '错题', '复盘', 'cuoti', 'fupan'] },
  { to: '/notebook', label: '错题本', desc: '错题录入 · 艾宾浩斯复习（拍照 OCR 收录）', kw: ['notebook', '错题本', 'cuoti', 'error'] },
  // 院校数据中心
  { to: '/kaoyan', label: '择校中心', desc: '院校库 · 对比 · 智能择校', kw: ['kaoyan', '择校', 'zk', '院校', 'yuanxiao'] },
  { to: '/kaoyan/schools', label: '院校库', desc: '院校数据浏览与详情', kw: ['schools', '院校库', 'yuanxiaoku'] },
  { to: '/kaoyan/compare', label: '院校对比', desc: '多校指标横向对比', kw: ['compare', '对比', 'duibi'] },
  { to: '/kaoyan/recommend', label: '智能择校', desc: '按画像推荐院校', kw: ['recommend', '推荐', 'tuijian'] },
  // 通用
  { to: '/', label: '仪表盘', desc: '今日概览与考研倒计时', kw: ['dashboard', '首页', '主页', 'shouye', 'kaoyan'] },
  { to: '/tasks', label: '任务打卡', desc: '今日任务与计划管理', kw: ['task', '任务', '待办', 'todo', 'renwu'] },
  { to: '/planner', label: '学习计划', desc: '规划与连续打卡', kw: ['planner', '计划', '规划', 'jihua', 'plan'] },
  { to: '/profile', label: '学习画像', desc: '学习数据与薄弱点', kw: ['profile', '画像', 'huaxiang'] },
  { to: '/assistant', label: 'AI 助手', desc: '问答与 RAG 检索', kw: ['assistant', 'ai', '助手', '问答', 'zhushou', 'chat'] },
  { to: '/settings', label: '设置', desc: '偏好与数据管理', kw: ['setting', '设置', '偏好', 'shezhi', 'config'] },
]

export default function CommandPalette({ onClose }) {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])
  useEffect(() => { setActive(0) }, [q])

  const results = useMemo(() => {
    const key = q.trim().toLowerCase()
    if (!key) return COMMANDS
    return COMMANDS.filter(
      (c) =>
        c.label.toLowerCase().includes(key) ||
        c.kw.some((k) => k.toLowerCase().includes(key))
    )
  }, [q])

  const go = (to) => { navigate(to); onClose() }

  const onKey = (e) => {
    if (e.key === 'Escape') { onClose(); return }
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => Math.min(i + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter') { if (results[active]) go(results[active].to) }
  }

  return (
    <div className="cmd-overlay" onClick={onClose}>
      <div className="cmd-panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="快捷跳转">
        <div className="cmd-input-row">
          <Search size={18} className="cmd-ico" />
          <input
            ref={inputRef}
            className="cmd-input"
            placeholder="搜索功能，快速跳转（如：错题 / quiz / 计划）"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
          />
          <kbd className="cmd-esc">ESC</kbd>
        </div>
        <div className="cmd-list">
          {results.length === 0 && <div className="cmd-empty">没有匹配的功能</div>}
          {results.map((c, i) => (
            <button
              key={c.to}
              className={`cmd-item ${i === active ? 'active' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(c.to)}
            >
              <span className="cmd-label">{c.label}</span>
              <span className="cmd-desc">{c.desc}</span>
              {i === active && <span className="cmd-enter">↵</span>}
            </button>
          ))}
        </div>
        <div className="cmd-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
          <span><kbd>↵</kbd> 跳转</span>
          <span><kbd>esc</kbd> 关闭</span>
        </div>
      </div>
    </div>
  )
}
