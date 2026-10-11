import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from './Icon'

/* 命令面板数据：路由 + 中文名 + 描述 + 搜索关键词（中英文/拼音，方便模糊搜索） */
const COMMANDS = [
  { to: '/', label: '仪表盘', desc: '今日概览与考研倒计时', kw: ['dashboard', '首页', '主页', 'shouye', 'kaoyan'] },
  { to: '/tasks', label: '任务打卡', desc: '今日任务与计划管理', kw: ['task', '任务', '待办', 'todo', 'renwu'] },
  { to: '/kbmap', label: '知识地图', desc: '章节→知识点→题型与复习进度', kw: ['kb', '知识地图', '考点', '章节', 'zhishi', 'map', 'taxonomy'] },
  { to: '/quiz', label: '刷题中心', desc: '题库与错题强化', kw: ['quiz', '刷题', '题库', 'shuati', 'test'] },
  { to: '/notebook', label: '错题本', desc: '错题归集与复习', kw: ['notebook', '错', '题', 'cuoti', 'error'] },
  { to: '/words', label: '单词记忆', desc: '单词背诵与发音', kw: ['word', '单词', '词', 'danci', 'vocab'] },
  { to: '/cards', label: '记忆卡片', desc: 'Anki 式间隔复习', kw: ['card', '卡片', 'kapian', 'flash'] },
  { to: '/documents', label: '文档知识库', desc: '资料与知识图谱', kw: ['document', '文档', '资料', 'wendang', 'file'] },
  { to: '/pan', label: '网盘联动', desc: '云盘与同步', kw: ['pan', '网盘', '云盘', 'wangpan', 'cloud'] },
  { to: '/planner', label: '学习计划', desc: '规划与连续打卡', kw: ['planner', '计划', '规划', 'jihua', 'plan'] },
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
