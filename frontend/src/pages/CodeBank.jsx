import React, { useCallback, useEffect, useState } from 'react'
import { request } from '../api/client'
import './CodeBank.css'

const DIFF_COLOR = { easy: '#16a34a', medium: '#f59e0b', hard: '#ef4444' }
const DIFF_CN = { easy: '简单', medium: '中等', hard: '困难' }
const STARS = (n) => '★'.repeat(n || 0) + '☆'.repeat(Math.max(0, 5 - (n || 0)))

export default function CodeBank() {
  const [tab, setTab] = useState('panorama') // panorama | list | strategy
  const [subjects, setSubjects] = useState([])
  const [subject, setSubject] = useState('')
  const [pano, setPano] = useState(null)
  const [list, setList] = useState(null)
  const [strategy, setStrategy] = useState(null)
  const [detail, setDetail] = useState(null)
  const [filters, setFilters] = useState({ q: '', difficulty: '', tag: '', min_frequency: 0 })
  const [showAdd, setShowAdd] = useState(false)
  const [newSub, setNewSub] = useState({ name: '', direction: '' })
  const [lang, setLang] = useState('')

  const loadSubjects = useCallback(() => {
    request('/codebank/subjects').then(setSubjects).catch(() => {})
  }, [])
  useEffect(() => { loadSubjects() }, [loadSubjects])

  useEffect(() => {
    if (tab === 'panorama') request('/codebank/panorama', { params: subject ? { subject } : {} }).then(setPano).catch(() => {})
    if (tab === 'strategy') request('/codebank/exam-strategy').then(setStrategy).catch(() => {})
    if (tab === 'list') {
      const params = {}
      if (subject) params.subject = subject
      if (filters.q) params.q = filters.q
      if (filters.difficulty) params.difficulty = filters.difficulty
      if (filters.tag) params.tag = filters.tag
      if (filters.min_frequency) params.min_frequency = filters.min_frequency
      request('/codebank/questions', { params }).then(setList).catch(() => {})
    }
  }, [tab, subject, filters])

  const openDetail = (id) => {
    request('/codebank/questions/' + id).then(d => { setDetail(d); setLang(d.languages?.[0] || '') }).catch(() => {})
  }
  const addSubject = () => {
    if (!newSub.name.trim()) return
    request('/codebank/subjects', { method: 'POST', body: newSub })
      .then(r => { if (r.added) { loadSubjects(); setNewSub({ name: '', direction: '' }); setShowAdd(false) } })
      .catch(() => {})
  }

  return (
    <div className="cb-wrap">
      <header className="cb-hero">
        <div>
          <h1>💻 复试代码题库</h1>
          <p>LeetCode 式刷题 · 知识点全景 · 考频分析 —— 数学/数电/模电/信号/光学/408/复试上机，科目随时可加</p>
        </div>
        <button className="cb-add" onClick={() => setShowAdd(true)}>＋ 添加科目</button>
      </header>

      <div className="cb-subjects">
        <button className={`cb-chip ${subject === '' ? 'on' : ''}`} onClick={() => setSubject('')}>全部</button>
        {subjects.map(s => (
          <button key={s.id} className={`cb-chip ${subject === s.name ? 'on' : ''}`}
            title={`${s.direction || ''} · ${s.question_count} 题`}
            onClick={() => setSubject(s.name)}>{s.name}<em>{s.question_count}</em></button>
        ))}
      </div>

      <div className="cb-tabs" role="tablist">
        {[['panorama', '🗺 知识点全景'], ['list', '📋 题库列表'], ['strategy', '📊 考频分析']].map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k}
            className={`cb-tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {/* ---------- 知识点全景 ---------- */}
      {tab === 'panorama' && pano && (
        <div className="cb-pano">
          {pano.items.map(it => (
            <button key={it.tag} className="cb-pano-card" onClick={() => { setFilters(f => ({ ...f, tag: it.tag })); setTab('list') }}>
              <div className="cb-pano-tag">{it.tag}</div>
              <div className="cb-pano-meta">{it.subject} · {it.total} 题</div>
              <div className="cb-pano-freq">{STARS(Math.round(it.avg_frequency))}</div>
              {it.hot && <div className="cb-pano-hot">最热：{it.hot.title}</div>}
            </button>
          ))}
        </div>
      )}

      {/* ---------- 题库列表 ---------- */}
      {tab === 'list' && (
        <>
          <div className="cb-filters">
            <input className="cb-search" placeholder="搜索题目标题/题面…" value={filters.q}
              onChange={e => setFilters(f => ({ ...f, q: e.target.value }))} />
            {[['', '全部难度'], ['easy', '简单'], ['medium', '中等'], ['hard', '困难']].map(([v, l]) => (
              <button key={v || 'all'} className={`cb-chip ${filters.difficulty === v ? 'on' : ''}`}
                onClick={() => setFilters(f => ({ ...f, difficulty: v }))}>{l}</button>
            ))}
            {[0, 4, 5].map(n => (
              <button key={n} className={`cb-chip ${filters.min_frequency === n ? 'on' : ''}`}
                onClick={() => setFilters(f => ({ ...f, min_frequency: n }))}>
                {n === 0 ? '不限考频' : `${'★'.repeat(n)}+`}
              </button>
            ))}
          </div>
          <table className="cb-table">
            <thead><tr><th>#</th><th>题目</th><th>科目</th><th>难度</th><th>考频</th><th>年份</th></tr></thead>
            <tbody>
              {(list?.items || []).map(q => (
                <tr key={q.id} onClick={() => openDetail(q.id)}>
                  <td>{q.id}</td>
                  <td className="cb-title">{q.title}</td>
                  <td>{q.subject}</td>
                  <td><em style={{ color: DIFF_COLOR[q.difficulty], fontStyle: 'normal' }}>{DIFF_CN[q.difficulty]}</em></td>
                  <td className="cb-freq">{STARS(q.frequency)}</td>
                  <td className="cb-years">{(q.appear_years || []).join('/') || '—'}</td>
                </tr>
              ))}
              {list && list.items.length === 0 && <tr><td colSpan="6" className="cb-empty">没有匹配的题目</td></tr>}
            </tbody>
          </table>
        </>
      )}

      {/* ---------- 考频分析 ---------- */}
      {tab === 'strategy' && strategy && (
        <div className="cb-strategy">
          <h3>🔥 高频题 TOP10（按考频标注）</h3>
          <div className="cb-top-grid">
            {strategy.top_questions.map((q, i) => (
              <button key={q.id} className="cb-top-card" onClick={() => openDetail(q.id)}>
                <em className={`cb-top-rank ${i < 3 ? 'hot' : ''}`}>{i + 1}</em>
                <div>
                  <div className="cb-title">{q.title}</div>
                  <div className="cb-pano-meta">{q.subject} · <em style={{ color: DIFF_COLOR[q.difficulty], fontStyle: 'normal' }}>{DIFF_CN[q.difficulty]}</em> · {(q.appear_years || []).join('/') || '—'}</div>
                </div>
                <span className="cb-freq">{STARS(q.frequency)}</span>
              </button>
            ))}
          </div>
          <h3>科目分布（题数 × 平均考频）</h3>
          <div className="cb-dist">
            {strategy.by_subject.map(s => (
              <div key={s.subject} className="cb-dist-row">
                <span className="cb-dist-name">{s.subject}</span>
                <span className="cb-dist-bar"><i style={{ width: `${Math.min(100, s.count * 12)}%` }} /></span>
                <span className="cb-dist-num">{s.count} 题 · 均{s.avg_frequency}★</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ---------- 详情弹层 ---------- */}
      {detail && (
        <div className="cb-mask" onClick={() => setDetail(null)}>
          <article className="cb-detail" onClick={e => e.stopPropagation()}>
            <header className="cb-detail-head">
              <div>
                <span className={`cb-diff ${detail.difficulty}`}>{DIFF_CN[detail.difficulty]}</span>
                <strong>{detail.title}</strong>
                <span className="cb-freq">{STARS(detail.frequency)}</span>
              </div>
              <button className="cb-close" onClick={() => setDetail(null)}>✕</button>
            </header>
            <div className="cb-detail-meta">
              {detail.subject} · {(detail.tags || []).map(t => <code key={t}>{t}</code>)}
              {detail.appear_years?.length > 0 && <span> · 出现年份：{detail.appear_years.join('/')}</span>}
            </div>
            <pre className="cb-statement">{detail.statement}</pre>
            {detail.input_desc && <p className="cb-io"><b>输入：</b>{detail.input_desc}</p>}
            {detail.output_desc && <p className="cb-io"><b>输出：</b>{detail.output_desc}</p>}
            {(detail.examples || []).map((ex, i) => (
              <div key={i} className="cb-example">
                <div>示例 {i + 1}</div>
                <pre>{ex.input}</pre>
                <pre className="out">{ex.output}</pre>
              </div>
            ))}
            {detail.hint && <div className="cb-hint">💡 提示：{detail.hint}</div>}
            {detail.languages?.length > 0 && (
              <>
                <div className="cb-langs">
                  {detail.languages.map(l => (
                    <button key={l} className={`cb-chip ${lang === l ? 'on' : ''}`} onClick={() => setLang(l)}>{l}</button>
                  ))}
                </div>
                <pre className="cb-code">{TEMPLATE(detail, lang)}</pre>
              </>
            )}
            <div className="cb-note">本地自测：复制模板到本地 IDE 运行；上机判题与提交记录将在后续版本接入。</div>
          </article>
        </div>
      )}

      {/* ---------- 添加科目弹层 ---------- */}
      {showAdd && (
        <div className="cb-mask" onClick={() => setShowAdd(false)}>
          <div className="cb-detail cb-add-panel" onClick={e => e.stopPropagation()}>
            <h3>添加科目模块</h3>
            <input className="cb-search" placeholder="科目名，如：光纤通信 / 嵌入式 / 复试英语口语"
              value={newSub.name} onChange={e => setNewSub(s => ({ ...s, name: e.target.value }))} />
            <input className="cb-search" placeholder="方向（可选），如：复试·通信"
              value={newSub.direction} onChange={e => setNewSub(s => ({ ...s, direction: e.target.value }))} />
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button className="cb-chip on" onClick={addSubject}>确认添加</button>
              <button className="cb-chip" onClick={() => setShowAdd(false)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* 按语言返回入门模板（题库暂不存逐题模板，统一起步骨架，降低维护成本） */
function TEMPLATE(detail, lang) {
  const skeletons = {
    'C++': '#include <bits/stdc++.h>\nusing namespace std;\nint main() {\n    // 在此实现\n    return 0;\n}',
    'Python': 'def solve():\n    # 在此实现\n    pass\n\nif __name__ == "__main__":\n    print(solve())',
    'C': '#include <stdio.h>\nint main() {\n    /* 在此实现 */\n    return 0;\n}',
    'Java': 'public class Main {\n    public static void main(String[] args) {\n        // 在此实现\n    }\n}',
  }
  return skeletons[lang] || '// 选择语言'
}
