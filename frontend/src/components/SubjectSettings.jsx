import React, { useEffect, useState } from 'react'
import { goalsApi } from '../api/client'
import { toast } from './UI'
import { CheckCircle, RefreshCw } from '../components/Icon'

/**
 * 备考科目设置：决定进度统计口径、AI 分科路由、资料归类、出题范围。
 *
 * 分两层：
 *  考试科目 —— 你实际要考的（计入复习进度）
 *  支撑科目 —— 可能涉及、要能查资料出题的（不计入进度）
 *
 * 改这里，全应用的科目口径一起变，不用改代码。
 */
export default function SubjectSettings() {
  const [cfg, setCfg] = useState(null)
  const [status, setStatus] = useState('loading')
  const [saving, setSaving] = useState(false)
  const [exam, setExam] = useState([])
  const [support, setSupport] = useState([])

  const load = () => {
    setStatus('loading')
    goalsApi.subjects()
      .then((d) => {
        setCfg(d)
        setExam(d.exam_subjects || [])
        setSupport(d.support_subjects || [])
        setStatus('ok')
      })
      .catch(() => setStatus('error'))
  }

  useEffect(() => { load() }, [])

  if (status === 'loading') {
    return <section className="card"><div className="card-body"><div className="loading-inline">读取科目配置…</div></div></section>
  }
  if (status === 'error' || !cfg) {
    return (
      <section className="card">
        <div className="card-body">
          <div className="empty-hint">读取失败，请确认后端已启动。</div>
          <button className="btn ghost" onClick={load}>重试</button>
        </div>
      </section>
    )
  }

  const toggle = (list, setList, name) => {
    setList(list.includes(name) ? list.filter((x) => x !== name) : [...list, name])
  }

  const save = async () => {
    setSaving(true)
    try {
      const d = await goalsApi.updateSubjects({
        exam_subjects: exam,
        support_subjects: support,
      })
      setCfg(d)
      setExam(d.exam_subjects || [])
      setSupport(d.support_subjects || [])
      toast(d.ignored?.length ? `已保存（忽略无法识别的：${d.ignored.join('、')}）` : '科目配置已保存')
    } catch (e) {
      toast(`保存失败：${e.message}`)
    }
    setSaving(false)
  }

  const resetDefault = () => {
    setExam(cfg.core_defaults || [])
    setSupport(cfg.major_defaults || [])
  }

  const dirty =
    JSON.stringify([...exam].sort()) !== JSON.stringify([...(cfg.exam_subjects || [])].sort()) ||
    JSON.stringify([...support].sort()) !== JSON.stringify([...(cfg.support_subjects || [])].sort())

  const groups = [
    { key: 'exam', title: '考试科目', desc: '你实际要考的，计入复习进度与薄弱统计', list: exam, setList: setExam },
    { key: 'support', title: '专业课支撑科目', desc: '可能涉及、要能查资料出题，但不计入进度', list: support, setList: setSupport },
  ]

  return (
    <section className="card subject-settings">
      <div className="card-head">
        <div>
          <div className="card-title">备考科目</div>
          <div className="card-sub">
            决定进度统计口径、AI 分科选模型、资料归类与出题范围 —— 改这里不用改代码
          </div>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={resetDefault}>恢复默认</button>
          <button className="btn ghost" onClick={load}><RefreshCw size={14} /> 重新读取</button>
          <button className="btn primary" onClick={save} disabled={saving || !dirty}>
            {saving ? '保存中…' : dirty ? '保存' : '已保存'}
          </button>
        </div>
      </div>

      <div className="card-body">
        {cfg.using_default && (
          <div className="ss-hint">
            当前使用默认口径。可以按自己的实际情况增减科目。
          </div>
        )}

        {groups.map((g) => (
          <div className="ss-group" key={g.key}>
            <div className="ss-group-head">
              <span className="ss-group-title">{g.title}</span>
              <span className="ss-group-desc">{g.desc}</span>
              <span className="ss-group-count">已选 {g.list.length}</span>
            </div>
            <div className="ss-chips">
              {cfg.all_known.map((name) => {
                const on = g.list.includes(name)
                const meta = cfg.subject_meta[name] || {}
                return (
                  <button
                    key={name}
                    className={`chip ${on ? 'active' : ''}`}
                    onClick={() => toggle(g.list, g.setList, name)}
                    title={`章节 ${(meta.chapters || []).length} · 题型 ${(meta.question_types || []).join('/')}`}
                  >
                    {on && <CheckCircle size={12} />}
                    {name}
                    <small>{(meta.chapters || []).length}章</small>
                  </button>
                )
              })}
            </div>
          </div>
        ))}

        {/* 当前生效效果预览 */}
        <div className="ss-preview">
          <div className="ss-preview-title">当前口径生效后：</div>
          <ul>
            <li>复习进度与薄弱考点统计 <b>{exam.length}</b> 科：{exam.join('、') || '（空）'}</li>
            <li>AI 分科选模型覆盖 <b>{exam.length + support.length}</b> 科</li>
            <li>资料可归类到 <b>{cfg.all_known.length}</b> 个科目（含拓展）</li>
          </ul>
        </div>

        <details className="ss-help">
          <summary>这两层的区别是什么？</summary>
          <ul>
            <li>
              <b>考试科目</b>：真正会出现在你成绩单上的。知识地图的进度、
              薄弱考点排名只算这几科 —— 否则把没考的科目算进来，进度就是假的。
            </li>
            <li>
              <b>支撑科目</b>：可能是备选院校的专业课、或者要用来补基础的。
              资料能录入、能检索、能出题、AI 也会按科目选模型，
              但不计入"我复习到哪了"。
            </li>
            <li>
              两层的并集 = AI 分科路由的范围。提问时系统会自动识别科目并选对应模型。
            </li>
          </ul>
        </details>
      </div>
    </section>
  )
}
