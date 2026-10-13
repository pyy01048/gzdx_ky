import React, { useEffect, useState } from 'react'
import { goalsApi, taxonomyApi } from '../api/client'
import { toast } from './UI'
import { CheckCircle, RefreshCw, Plus } from '../components/Icon'

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
  const [newSubject, setNewSubject] = useState('')
  const [adding, setAdding] = useState(false)
  const [addToLayer, setAddToLayer] = useState('exam') // 新科目默认加入哪一层

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

  /** 新增自定义科目：注册到科目字典（subject_config 表）并勾选进指定层。 */
  const addCustomSubject = async () => {
    const name = newSubject.trim()
    if (!name) return toast('请输入科目名')
    if (cfg.all_known.includes(name) || exam.includes(name) || support.includes(name)) {
      return toast('该科目已存在')
    }
    setAdding(true)
    try {
      // 1) 注册到科目字典（is_custom=True），后端 normalize 之后认识它
      await taxonomyApi.createSubject({ subject: name })
      // 2) 勾选进指定层
      if (addToLayer === 'exam') setExam((l) => [...l, name])
      else setSupport((l) => [...l, name])
      // 3) 刷新字典列表，让新科目立刻出现在下方候选里
      const d = await goalsApi.subjects()
      setCfg(d)
      setNewSubject('')
      toast(`已新增自定义科目「${name}」，点击右上角「保存」生效`)
    } catch (e) {
      toast(`新增失败：${e.message || '未知错误'}`)
    } finally {
      setAdding(false)
    }
  }

  const dirty =
    JSON.stringify([...exam].sort()) !== JSON.stringify([...(cfg.exam_subjects || [])].sort()) ||
    JSON.stringify([...support].sort()) !== JSON.stringify([...(cfg.support_subjects || [])].sort())

  /* 与 0854 电子信息考研无关的预置科目（0 章或联考/医学/教育等），默认折叠隐藏 */
  const IRRELEVANT_SUBJECTS = ['管理类联考综合','经济类联考综合','法律硕士专业基础','教育学专业基础',
    '心理学专业基础','西医综合','中医综合','其他','网络补充']
  const showExt = exam.concat(support).some((s) => IRRELEVANT_SUBJECTS.includes(s)) || (cfg.custom_subjects || []).length > 0

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
            已隐藏与考研无关的预置科目（管理类联考、医学、教育等），如需恢复请在下方「恢复默认」后重新勾选。
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
              {cfg.all_known.filter((name) => !IRRELEVANT_SUBJECTS.includes(name) || g.list.includes(name)).map((name) => {
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

        {/* 自定义新增科目：预置池里没有的科目可自己加，改这里不用改代码 */}
        <div className="ss-group" style={{ marginTop: 14 }}>
          <div className="ss-group-head">
            <span className="ss-group-title">新增自定义科目</span>
            <span className="ss-group-desc">预置池里没有的科目（如另一门专业课），加进来后全站可用</span>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              className="input"
              style={{ flex: '1 1 200px', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)' }}
              placeholder="输入科目名，如：信号与系统 / 自控原理 / 数据结构"
              value={newSubject}
              onChange={(e) => setNewSubject(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addCustomSubject() }}
            />
            <select
              className="input"
              style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-2)' }}
              value={addToLayer}
              onChange={(e) => setAddToLayer(e.target.value)}
            >
              <option value="exam">加入考试科目</option>
              <option value="support">加入支撑科目</option>
            </select>
            <button className="btn primary" onClick={addCustomSubject} disabled={adding || !newSubject.trim()}>
              <Plus size={14} /> {adding ? '添加中…' : '添加'}
            </button>
          </div>
          {(exam.some((s) => !cfg.all_known.includes(s)) || support.some((s) => !cfg.all_known.includes(s))) && (
            <div className="ss-hint" style={{ marginTop: 8 }}>
              含自定义科目：{[...exam, ...support].filter((s) => !cfg.all_known.includes(s)).join('、')}
            </div>
          )}
        </div>

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
