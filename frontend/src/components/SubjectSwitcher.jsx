import React, { useEffect, useState } from 'react'
import useStore from '../store/useStore'
import { useSubjectConfig, subjectLabel } from '../hooks/useSubjectConfig'
import { Target, ChevronDown } from './Icon'
import './SubjectSwitcher.css'

/* ==========================================================================
   顶部科目切换器（可收缩）
   --------------------------------------------------------------------------
   用户诉求：「顶部科目选择要可收缩」——把原先散落在各页面内部的科目导航
   收敛到全局顶栏一处，且整条栏可以收起来，不占版面。

   数据来源：科目清单一律来自 useSubjectConfig（后端 GET /api/goals/subjects，
   与「设置 → 备考科目」同一份配置），**不硬编码任何科目**；
   选中的科目写进全局 store（store/useStore.js 的 currentSubject），
   供各页面统一消费。

   收缩状态持久化到 localStorage（与侧边栏 nav_modules_open 同一做法），
   刷新后保持用户上次的收起/展开选择。
   ========================================================================== */

const COLLAPSE_KEY = 'subject_bar_collapsed'

function loadCollapsed() {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

export default function SubjectSwitcher() {
  const { active, ready } = useSubjectConfig()          // 科目清单（API 单一来源）
  const currentSubject = useStore((s) => s.currentSubject)
  const setCurrentSubject = useStore((s) => s.setCurrentSubject)
  const [collapsed, setCollapsed] = useState(loadCollapsed)

  /* 当前科目被移出配置（设置页删科目）时回落「全部科目」，
     否则顶栏会一直显示一个已不存在的科目，让人以为筛选还生效。 */
  useEffect(() => {
    if (ready && currentSubject && !active.includes(currentSubject)) {
      setCurrentSubject('')
    }
  }, [ready, currentSubject, active, setCurrentSubject])

  const toggle = () => {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0') } catch { /* 隐私模式忽略 */ }
  }

  const pick = (v) => setCurrentSubject(v)

  return (
    <section className={`subject-bar ${collapsed ? 'collapsed' : ''}`} aria-label="科目切换">
      <div className="sb-head">
        <Target size={15} className="sb-ico" />
        <span className="sb-title">当前科目</span>
        <span className="sb-current">{currentSubject ? subjectLabel(currentSubject) : '全部科目'}</span>
        <button
          className="sb-toggle"
          onClick={toggle}
          aria-expanded={!collapsed}
          title={collapsed ? '展开科目切换' : '收起科目切换'}
        >
          {collapsed ? '展开' : '收起'}
          <ChevronDown size={13} className={`sb-caret ${collapsed ? '' : 'open'}`} />
        </button>
      </div>
      {!collapsed && (
        <div className="sb-list" role="listbox" aria-label="选择科目">
          <button
            className={`sb-chip ${!currentSubject ? 'on' : ''}`}
            role="option"
            aria-selected={!currentSubject}
            onClick={() => pick('')}
          >
            全部科目
          </button>
          {active.map((s) => (
            <button
              key={s}
              className={`sb-chip ${currentSubject === s ? 'on' : ''}`}
              role="option"
              aria-selected={currentSubject === s}
              onClick={() => pick(s)}
            >
              {subjectLabel(s)}
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
